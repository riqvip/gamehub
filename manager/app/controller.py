"""Private, authenticated capability API. Never publish its port to the host."""

import asyncio
import logging
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import backups, code_mods, config, game_settings, mods
from . import docker_service as ds
from .downloads import download
from .http_security import SecurityMiddleware
from .models import (
    ActionRequest,
    BackupPolicy,
    CreateServerRequest,
    ModAction,
    RestoreRequest,
    RuntimeChange,
    Settings,
    URLInstall,
)

log = logging.getLogger("gamehub.controller")


@asynccontextmanager
async def lifespan(app):
    ds.initialize()
    shutdown = threading.Event()

    def scheduled():
        while not shutdown.wait(30):
            try:
                backups.schedule_tick()
            except Exception:
                log.exception("Backup scheduler failed")

    thread = threading.Thread(target=scheduled, daemon=True)
    thread.start()
    yield
    shutdown.set()
    for event in ds._cancel.values():
        event.set()
    for inst in ds.list_instances():
        if inst.get("job", {}).get("state") == "running":
            ds.stop(inst["id"])


app = FastAPI(
    title="GameHub restricted controller", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
)
app.add_middleware(SecurityMiddleware)


def controller_auth(request: Request):
    if not config.CONTROLLER_TOKEN or not secrets.compare_digest(
        request.headers.get("authorization", "").encode(), ("Bearer " + config.CONTROLLER_TOKEN).encode()
    ):
        raise HTTPException(401, "Controller authentication required")


@app.get("/healthz")
def health():
    return {"status": "ok", "component": "controller"}


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)[:500]}, status_code=409)


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({"detail": "Requested resource not found"}, status_code=404)


@app.exception_handler(Exception)
async def failed(request, exc):
    log.error("Controller operation failed: %s", type(exc).__name__)
    return JSONResponse(
        {"detail": "Controller operation failed. Check local service logs and game logs."}, status_code=502
    )


api = APIRouter(prefix="/v1", dependencies=[Depends(controller_auth)])


@api.get("/servers")
def servers():
    return [ds.public(inst) for inst in ds.list_instances()]


@api.post("/servers", status_code=201)
def create(body: CreateServerRequest):
    return ds.create_instance(body)


@api.get("/servers/{sid}")
def server(sid: str):
    with ds.locked(sid, allow_job=True):
        return ds.public(ds.get_instance(sid))


@api.post("/servers/{sid}/actions")
def lifecycle(sid: str, body: ActionRequest):
    if body.action == "cancel":
        return ds.cancel_install(sid)
    if body.action in ("install", "update"):
        return ds.begin_install(sid, body.action == "update")
    with ds.locked(sid):
        if body.action == "remove":
            return ds.delete_instance(sid, body.confirmation)
        return {"start": ds.start, "stop": ds.stop, "restart": ds.restart}[body.action](sid)


@api.post("/servers/{sid}/runtime")
def runtime_change(sid: str, body: RuntimeChange):
    if body.action == "convert":
        return ds.begin_convert(sid, body.confirmation, body.acknowledge_code_mods)
    return ds.rollback_runtime(sid, body.confirmation)


@api.get("/servers/{sid}/health")
def game_health(sid: str):
    with ds.locked(sid, allow_job=True):
        return ds.stats(sid)


@api.get("/servers/{sid}/logs")
def logs(sid: str):
    with ds.locked(sid, allow_job=True):
        return {"logs": ds.logs_tail(sid)}


@api.get("/servers/{sid}/players")
def players(sid: str):
    from .rest_helpers import players as game_players

    with ds.locked(sid):
        return {"players": game_players(sid)}


@api.post("/servers/{sid}/rcon")
def rcon(sid: str, body: dict):
    from .rcon_helpers import exec_rcon

    command = body.get("command", "")
    # Explicit game administration commands; no filesystem/exec capability.
    allowed = ("Info", "ShowPlayers", "Save", "Broadcast", "KickPlayer", "BanPlayer")
    if (
        set(body) != {"command"}
        or not isinstance(command, str)
        or not command
        or len(command) > 512
        or any(ord(c) < 32 for c in command)
        or command.split(" ")[0] not in allowed
    ):
        raise ValueError("Unsupported RCON command")
    with ds.locked(sid):
        return {"output": exec_rcon(sid, command)}


@api.get("/servers/{sid}/settings")
def settings(sid: str):
    return game_settings.get_settings(sid)


@api.put("/servers/{sid}/settings")
def save_settings(sid: str, body: dict):
    with ds.locked(sid):
        current = ds.get_instance(sid)["settings"]
        return ds.update_settings(sid, Settings.model_validate(current | body))


@api.get("/servers/{sid}/mods")
def mod_list(sid: str):
    with ds.locked(sid, allow_job=True):
        return mods.list_mods(sid)


@api.post("/servers/{sid}/mods/upload", status_code=201)
async def upload(sid: str, request: Request):
    controller_auth(request)
    with tempfile.TemporaryDirectory(prefix="upload-", dir=config.CONFIG_DIR) as temp:
        target = Path(temp) / "upload"
        total = 0
        with target.open("xb") as output:
            async for chunk in request.stream():
                total += len(chunk)
                if total > config.MAX_UPLOAD:
                    raise HTTPException(413, "Upload size limit exceeded")
                output.write(chunk)
        filename = request.headers.get("x-filename", "")
        update_id = request.headers.get("x-update-id", "")

        def install():
            with ds.locked(sid):
                return mods.install(sid, target, filename, update_id)

        return await asyncio.to_thread(install)


@api.post("/servers/{sid}/mods/url", status_code=201)
def url_install(sid: str, body: URLInstall):
    with ds.locked(sid):
        ds.require_stopped(sid)
        with tempfile.TemporaryDirectory(prefix="download-", dir=config.CONFIG_DIR) as temp:
            target = Path(temp) / "download"
            download(body.url, target, body.sha256)
            # Never persist signed URL queries or authentication parameters.
            from urllib.parse import urlsplit

            return mods.install(
                sid, target, body.filename, body.update_id, "HTTPS: " + (urlsplit(body.url).hostname or "")
            )


@api.post("/servers/{sid}/mods/{mid}/actions")
def mod_action(sid: str, mid: str, body: ModAction):
    with ds.locked(sid):
        return mods.action(sid, mid, body.action, body.acknowledge_unverified)


@api.get("/servers/{sid}/code-mods")
def code_mod_list(sid: str):
    with ds.locked(sid, allow_job=True):
        return code_mods.list_mods(sid)


@api.post("/servers/{sid}/code-mods/upload", status_code=201)
async def code_mod_upload(sid: str, request: Request):
    controller_auth(request)
    with tempfile.TemporaryDirectory(prefix="upload-", dir=config.CONFIG_DIR) as temp:
        target = Path(temp) / "upload"
        total = 0
        with target.open("xb") as output:
            async for chunk in request.stream():
                total += len(chunk)
                if total > config.MAX_UPLOAD:
                    raise HTTPException(413, "Upload size limit exceeded")
                output.write(chunk)
        filename = request.headers.get("x-filename", "")

        def install():
            with ds.locked(sid):
                return code_mods.install(sid, target, filename)

        return await asyncio.to_thread(install)


@api.post("/servers/{sid}/code-mods/install-pwp", status_code=201)
def code_mod_install_pwp(sid: str):
    with ds.locked(sid):
        return code_mods.install_pwp(sid)


@api.post("/servers/{sid}/code-mods/{mid}/actions")
def code_mod_action(sid: str, mid: str, body: ModAction):
    with ds.locked(sid):
        return code_mods.action(sid, mid, body.action, body.acknowledge_unverified)


@api.get("/servers/{sid}/backups")
def backup_list(sid: str):
    return {
        "backups": backups.list_backups(sid),
        "policy": ds.get_instance(sid)["backup_policy"],
        "schedule": backups.read_json(backups.directory(sid) / "schedule-status.json", {}),
    }


@api.post("/servers/{sid}/backups", status_code=201)
def backup(sid: str):
    with ds.locked(sid):
        return backups.create_backup(sid)


@api.put("/servers/{sid}/backups/policy")
def backup_policy(sid: str, body: BackupPolicy):
    with ds.locked(sid):
        inst = ds.get_instance(sid)
        inst["backup_policy"] = body.model_dump()
        ds.save(inst)
        return body


@api.post("/servers/{sid}/backups/restore")
def restore(sid: str, body: RestoreRequest):
    with ds.locked(sid):
        return backups.restore(sid, **body.model_dump())


@api.delete("/servers/{sid}/backups/{filename}")
def delete_backup(sid: str, filename: str):
    with ds.locked(sid):
        return backups.delete_backup(sid, filename)


app.include_router(api)
