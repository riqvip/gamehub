"""Host-sensitive controller implementation. No generic Docker API is exposed."""

import ipaddress
import os
import re
import secrets
import shutil
import subprocess  # nosec B404
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import docker
from docker.errors import NotFound

from . import config
from .models import Settings
from .storage import _LOCK, atomic_json, checked, identifier, read_json

_docker = None
_locks = {}
_cancel = {}


def docker_client():
    global _docker
    if _docker is None:
        _docker = docker.from_env(timeout=20)
    return _docker


def initialize():
    os.umask(0o077)
    if len(config.CONTROLLER_TOKEN) < 43:
        raise RuntimeError("Controller token missing or too short")
    if not re.fullmatch(r"thijsvanloef/palworld-server-docker@sha256:[a-f0-9]{64}", config.PALWORLD_IMAGE):
        raise RuntimeError("PALWORLD_IMAGE must pin the approved Linux image by digest")
    if config.INSTALL_BACKEND not in ("steamcmd", "depotdownloader"):
        raise RuntimeError("Invalid installation backend")
    ipaddress.ip_address(config.GAME_BIND_IP)
    if Path(config.HOST_GAME_ROOT).is_absolute() is False or config.HOST_GAME_ROOT == "/":
        raise RuntimeError("Invalid host game root")
    for p in (config.CONFIG_DIR, config.GAME_ROOT, config.BACKUP_DIR):
        checked(p).mkdir(parents=True, exist_ok=True, mode=0o700)
    # Do not restart interrupted jobs or silently adopt containers.
    for inst in list_instances():
        job = inst.get("job", {})
        if job.get("state") == "running":
            inst["job"] = {
                **job,
                "state": "interrupted",
                "error": "Controller restarted. Inspect logs, then retry explicitly.",
            }
            save(inst)
            cont = get_container(inst["id"])
            if cont is not None:
                cont.stop(timeout=60)


def state_path(server_id):
    return checked(config.CONFIG_DIR, f"instances/{identifier(server_id)}.json")


def list_instances():
    root = checked(config.CONFIG_DIR, "instances")
    return [read_json(checked(root, p.name)) for p in sorted(root.glob("*.json"))] if root.exists() else []


def get_instance(server_id):
    inst = read_json(state_path(server_id))
    if inst is None:
        raise KeyError("Server not found")
    return inst


def save(inst):
    atomic_json(state_path(inst["id"]), inst)


@contextmanager
def locked(server_id, allow_job=False):
    identifier(server_id)
    with _LOCK:
        lock = _locks.setdefault(server_id, threading.RLock())
    with lock:
        if not allow_job and get_instance(server_id).get("job", {}).get("state") == "running":
            raise ValueError("An operation is in progress; wait or cancel it first")
        yield


def volume_path(server_id, volume_key="data"):
    get_instance(server_id)
    if volume_key != "data":
        raise ValueError("Only the managed data directory is available")
    return checked(config.GAME_ROOT, identifier(server_id))


def expected_labels(inst):
    return {"io.gamehub.owner": inst["owner"], "io.gamehub.instance": inst["id"]}


def get_container(server_id):
    inst = get_instance(server_id)
    if not inst.get("container_id"):
        return None
    client = docker_client()
    try:
        cont = client.containers.get(inst["container_id"])
    except NotFound:
        return None
    cont.reload()
    attrs = cont.attrs
    labels = attrs.get("Config", {}).get("Labels", {}) or {}
    if cont.id != inst["container_id"] or any(labels.get(k) != v for k, v in expected_labels(inst).items()):
        raise ValueError("Container ownership verification failed")
    host = attrs.get("HostConfig", {})
    if (
        host.get("Privileged")
        or host.get("NetworkMode") != config.GAME_NETWORK
        or host.get("CapAdd")
        or host.get("PidMode")
        or host.get("Devices")
    ):
        raise ValueError("Container policy verification failed")
    mounts = attrs.get("Mounts", [])
    expected = str(Path(config.HOST_GAME_ROOT) / inst["id"])
    if (
        len(mounts) != 1
        or mounts[0].get("Type") != "bind"
        or mounts[0].get("Source") != expected
        or mounts[0].get("Destination") != "/palworld"
    ):
        raise ValueError("Container mount verification failed")
    # Image digest and immutable Docker ID, not container names, establish ownership.
    if attrs.get("Config", {}).get("Image") != config.PALWORLD_IMAGE:
        raise ValueError("Container image verification failed")
    return cont


def container_state(server_id):
    cont = get_container(server_id)
    return cont.status if cont else "missing"


def require_stopped(server_id):
    cont = get_container(server_id)
    if cont and cont.status not in ("exited", "created", "dead"):
        raise ValueError("Stop the server before changing files or restoring backups")


def create_instance(body):
    with _LOCK:
        sid = "gh-" + body.name
        if state_path(sid).exists():
            raise ValueError("Server already exists")
        if len(list_instances()) >= 4:
            raise ValueError("Maximum four managed instances")
        if any(i["game_port"] == body.game_port for i in list_instances()):
            raise ValueError("Game port already allocated")
        root = checked(config.GAME_ROOT, sid)
        if root.exists():
            raise ValueError("Existing directory will not be adopted or overwritten")
        root.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(root, 1000, 1000)
        inst = {
            "id": sid,
            "name": body.name,
            "game": "palworld",
            "game_port": body.game_port,
            "owner": secrets.token_hex(32),
            "container_id": None,
            "installed": False,
            "settings": body.settings.model_dump(),
            "created_at": time.time(),
            "backup_policy": {"interval_hours": 0, "retain": 7},
            "last_backup": 0,
            "job": {"state": "idle", "log": []},
        }
        save(inst)
        return public(inst)


def public(inst):
    return {k: v for k, v in inst.items() if k not in ("owner", "container_id", "settings")} | {
        "state": container_state(inst["id"])
    }


def runtime_env(inst, setup=False):
    s = Settings.model_validate(inst["settings"])
    return {
        "PUID": "1000",
        "PGID": "1000",
        "PORT": "8211",
        "PLAYERS": str(s.players),
        "SERVER_NAME": s.server_name,
        "SERVER_DESCRIPTION": s.description,
        "ADMIN_PASSWORD": s.admin_password,
        "SERVER_PASSWORD": s.server_password,
        "COMMUNITY": "false",
        "RCON_ENABLED": "true",
        "RCON_PORT": "25575",
        "REST_API_ENABLED": "false",
        "MOD_ENABLED": "false",
        "BACKUP_ENABLED": "false",
        "AUTO_UPDATE_ENABLED": "false",
        "AUTO_REBOOT_ENABLED": "false",
        "UPDATE_ON_BOOT": str(setup).lower(),
        "SETUP_ONLY": str(setup).lower(),
        "USE_DEPOT_DOWNLOADER": str(config.INSTALL_BACKEND == "depotdownloader").lower(),
        "LOG_LEVEL": "INFO",
        "TZ": "UTC",
    }


def ensure_container(server_id, setup=False):
    inst = get_instance(server_id)
    cont = get_container(server_id)
    if cont:
        return cont
    # Collision is an error; never inspect/stop/delete a same-name container.
    root = volume_path(server_id)
    if shutil.disk_usage(root).free < config.MIN_FREE_BYTES:
        raise ValueError("Insufficient free disk space for Palworld")
    cont = docker_client().containers.create(
        config.PALWORLD_IMAGE,
        name=server_id,
        environment=runtime_env(inst, setup),
        ports={"8211/udp": (config.GAME_BIND_IP, inst["game_port"])},
        volumes={str(Path(config.HOST_GAME_ROOT) / server_id): {"bind": "/palworld", "mode": "rw"}},
        labels=expected_labels(inst),
        network=config.GAME_NETWORK,
        detach=True,
        init=True,
        privileged=False,
        cap_drop=["ALL"],
        cap_add=None,
        security_opt=["no-new-privileges:true"],
        user="1000:1000",
        mem_limit=config.GAME_MEMORY,
        nano_cpus=config.GAME_CPUS * 1_000_000_000,
        pids_limit=512,
        restart_policy={"Name": "no"},
        stop_signal="SIGTERM",
        tmpfs={"/tmp": "rw,nosuid,nodev,size=512m"},  # nosec B108
        log_config=docker.types.LogConfig(type="json-file", config={"max-size": "10m", "max-file": "3"}),
    )
    inst["container_id"] = cont.id
    save(inst)
    return cont


def remove_container(server_id):
    cont = get_container(server_id)
    if cont:
        require_stopped(server_id)
        cont.remove(v=False, force=False)
    inst = get_instance(server_id)
    inst["container_id"] = None
    save(inst)


def start(server_id):
    inst = get_instance(server_id)
    if not inst["installed"]:
        raise ValueError("Install the server first")
    require_stopped(server_id)
    from . import backups, mods

    backups.recover(server_id)
    mods.recover(server_id)
    cont = ensure_container(server_id)
    cont.start()
    return {"status": "started", "note": "Container started; game readiness is checked separately."}


def stop(server_id):
    cont = get_container(server_id)
    if cont and cont.status == "running":
        cont.stop(timeout=60)
    require_stopped(server_id)
    return {"status": "stopped"}


def restart(server_id):
    stop(server_id)
    return start(server_id)


def logs_tail(server_id, tail=200):
    cont = get_container(server_id)
    if not cont:
        return "No container created yet. Install the server first."
    output = cont.logs(tail=max(1, min(tail, 300))).decode("utf-8", errors="replace")[-100000:]
    for key in ("admin_password", "server_password"):
        value = get_instance(server_id)["settings"].get(key)
        if value:
            output = output.replace(value, "[redacted]")
    return output


def stats(server_id):
    cont = get_container(server_id)
    result = {
        "container_running": bool(cont and cont.status == "running"),
        "game_process_running": None,
        "game_initialized": None,
        "game_port_bound": None,
        "external_connectivity_verified": None,
        "cpu_percent": None,
        "mem_mb": None,
        "state": cont.status if cont else "missing",
    }
    if not result["container_running"]:
        return result
    data = cont.stats(stream=False)
    cpu = data.get("cpu_stats", {})
    previous = data.get("precpu_stats", {})
    delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - previous.get("cpu_usage", {}).get(
        "total_usage", 0
    )
    system = cpu.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
    result.update(
        cpu_percent=round(delta / system * cpu.get("online_cpus", 1) * 100, 1) if system > 0 else None,
        mem_mb=round(data.get("memory_stats", {}).get("usage", 0) / 1024**2, 1),
    )
    try:
        processes = cont.top().get("Processes", [])
        result["game_process_running"] = any("PalServer-Linux" in " ".join(p) for p in processes)
    except docker.errors.APIError:
        pass
    try:
        from .rcon_helpers import exec_rcon

        response = exec_rcon(server_id, "Info")
        result["game_initialized"] = "Pal Server" in response or "Palworld" in response
    except (OSError, ValueError):
        result["game_initialized"] = False
    return result


def update_settings(server_id, settings):
    require_stopped(server_id)
    inst = get_instance(server_id)
    remove_container(server_id)
    inst["container_id"] = None
    inst["settings"] = settings.model_dump()
    save(inst)
    return {"status": "saved", "note": "Settings apply on next start."}


def job_save(server_id, **values):
    with locked(server_id, allow_job=True):
        inst = get_instance(server_id)
        inst["job"].update(values)
        save(inst)


def job_log(server_id, message):
    log = get_instance(server_id)["job"].get("log", [])[-199:]
    job_save(server_id, log=log + [message[:500]])


def pull_image(server_id, cancel, deadline):
    # Separate process makes stalled client calls cancellable. No shell, no user command.
    proc = subprocess.Popen(  # nosec B603
        [sys.executable, "-m", "app.pull", config.PALWORLD_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        while proc.poll() is None:
            if cancel.wait(1) or time.monotonic() > deadline:
                raise TimeoutError("Installation cancelled or timed out")
        if proc.returncode:
            raise ValueError("Image pull failed; check registry connectivity and digest")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def run_install(server_id, cancel, update):
    deadline = time.monotonic() + config.INSTALL_TIMEOUT
    was_running = False
    try:
        job_log(server_id, "Checking disk, then pulling the configured image (no automatic retries).")
        if shutil.disk_usage(volume_path(server_id)).free < config.MIN_FREE_BYTES:
            raise ValueError("Insufficient free disk space")
        pull_image(server_id, cancel, deadline)
        with locked(server_id, allow_job=True):
            was_running = container_state(server_id) == "running"
            stop(server_id)
            if update:
                from .backups import create_backup

                create_backup(server_id, manage_stop=False)
            remove_container(server_id)
            if cancel.is_set():
                raise TimeoutError("Installation cancelled")
            cont = ensure_container(server_id, setup=True)
            cont.start()
        job_log(server_id, "Downloading/verifying Palworld. Live container logs show backend progress.")
        while True:
            if cancel.wait(2) or time.monotonic() > deadline:
                raise TimeoutError("Installation cancelled or timed out. Data retained; retry explicitly.")
            cont = get_container(server_id)
            if cont is None:
                raise ValueError("Installer container disappeared")
            if cont.status == "exited":
                if cont.attrs.get("State", {}).get("ExitCode") != 0:
                    raise ValueError("Palworld installer failed. Inspect container logs.")
                binary = checked(volume_path(server_id), "PalServer.sh")
                if not binary.is_file():
                    raise ValueError("Installer exited without the expected PalServer.sh")
                break
        with locked(server_id, allow_job=True):
            remove_container(server_id)
            inst = get_instance(server_id)
            inst["installed"] = True
            save(inst)
            ensure_container(server_id, setup=False)
            if was_running:
                start(server_id)
        job_log(server_id, "Installation verified. Game initialization is reported separately on Overview.")
        job_save(server_id, state="done", finished_at=time.time())
    except Exception as exc:
        try:
            with locked(server_id, allow_job=True):
                stop(server_id)
        except Exception:
            job_log(
                server_id, "Could not confirm installer stopped. Inspect the owned container before retrying."
            )
        job_save(
            server_id,
            state="cancelled" if cancel.is_set() else "error",
            error=str(exc)[:500],
            finished_at=time.time(),
        )


def begin_install(server_id, update=False):
    with locked(server_id):
        inst = get_instance(server_id)
        if inst["installed"] and not update:
            raise ValueError("Already installed; use Update explicitly")
        inst["job"] = {
            "state": "running",
            "kind": "update" if update else "install",
            "started_at": time.time(),
            "log": [],
            "error": "",
        }
        save(inst)
        cancel = threading.Event()
        _cancel[server_id] = cancel
        threading.Thread(target=run_install, args=(server_id, cancel, update), daemon=True).start()
    return {"status": "queued"}


def cancel_install(server_id):
    event = _cancel.get(server_id)
    if event is None or get_instance(server_id)["job"].get("state") != "running":
        raise ValueError("No active installation")
    event.set()
    return {"status": "cancelling"}


def delete_instance(server_id, confirmation):
    inst = get_instance(server_id)
    if confirmation != inst["name"]:
        raise ValueError("Type the server name to confirm removal")
    require_stopped(server_id)
    remove_container(server_id)
    # Keep all data and backups. Reuse of this name is deliberately blocked by its directory.
    state_path(server_id).unlink()
    return {"status": "removed", "note": "Game data and backups retained."}
