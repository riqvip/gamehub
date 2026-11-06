"""Unprivileged web UI. Only the private controller accesses Docker/game files."""

import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import auth, config, ip_gate
from .http_security import SecurityMiddleware
from .models import LoginRequest


@asynccontextmanager
async def lifespan(app):
    auth.validate()
    yield


app = FastAPI(
    title="GameHub", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
app.add_middleware(SecurityMiddleware)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.middleware("http")
async def ip_gate_middleware(request, call_next):
    if request.url.path != "/healthz" and not ip_gate.is_allowed(ip_gate.client_ip(request)):
        return JSONResponse({"detail": "Management access denied by IP policy"}, status_code=403)
    return await call_next(request)


@app.get("/healthz")
def health():
    return {"status": "ok", "component": "web"}


@app.post("/api/login")
def login(body: LoginRequest, request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/").split("://", 1)[-1] != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin login rejected")
    session, csrf = auth.verify_login(body.username, body.password, ip_gate.client_ip(request))
    response = JSONResponse({"csrf": csrf, "username": config.ADMIN_USER})
    response.set_cookie(
        "gamehub_session",
        session,
        max_age=config.SESSION_SECONDS,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/api/session")
def session(user=Depends(auth.require_auth)):
    return {"csrf": user["csrf"], "username": user["username"]}


@app.post("/api/logout")
def logout(request: Request, user=Depends(auth.require_auth)):
    with auth.database() as db:
        db.execute(
            "DELETE FROM sessions WHERE id=?", (auth.digest(request.cookies.get("gamehub_session", "")),)
        )
    auth.audit("logout")
    response = JSONResponse({"status": "signed out"})
    response.delete_cookie("gamehub_session", path="/")
    return response


@app.get("/api/activity")
def activity(user=Depends(auth.require_auth)):
    with auth.database() as db:
        rows = db.execute(
            "SELECT at, actor, action, target, outcome FROM audit ORDER BY rowid DESC LIMIT 200"
        ).fetchall()
    return [dict(zip(("at", "actor", "action", "target", "outcome"), r, strict=True)) for r in rows]


SID = r"gh-[a-z0-9][a-z0-9_-]{0,39}"
MID = r"mod-[a-f0-9]{16}"
CAPABILITIES = {
    "GET": [
        r"servers",
        rf"servers/{SID}",
        rf"servers/{SID}/(?:health|logs|players|settings|mods|code-mods|backups)",
    ],
    "POST": [
        r"servers",
        rf"servers/{SID}/(?:actions|rcon|mods/upload|mods/url|code-mods/upload|code-mods/install-pwp|runtime|backups|backups/restore)",
        rf"servers/{SID}/mods/{MID}/actions",
        rf"servers/{SID}/code-mods/{MID}/actions",
    ],
    "PUT": [rf"servers/{SID}/(?:settings|backups/policy)"],
    "DELETE": [rf"servers/{SID}/backups/[a-zA-Z0-9_-]+\.zip"],
}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def controller_proxy(path: str, request: Request, user=Depends(auth.require_auth)):
    if not any(re.fullmatch(p, path) for p in CAPABILITIES[request.method]):
        raise HTTPException(404, "Operation not available")
    headers = {"authorization": "Bearer " + config.CONTROLLER_TOKEN}
    for key in ("content-type", "x-filename", "x-update-id"):
        if key in request.headers:
            headers[key] = request.headers[key]
    status = "failed"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=5), trust_env=False) as client:
            response = await client.request(
                request.method,
                config.CONTROLLER_URL + "/v1/" + path,
                headers=headers,
                content=request.stream(),
            )
        status = str(response.status_code)
        return Response(response.content, status_code=response.status_code, media_type="application/json")
    except httpx.HTTPError:
        raise HTTPException(
            502, "Controller unavailable or timed out. Inspect the operation status before retrying."
        ) from None
    finally:
        if request.method != "GET":
            auth.audit(request.method, path, status)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "admin.html")
