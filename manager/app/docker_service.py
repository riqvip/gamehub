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
from .archives import files
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
    for image in (config.PALWORLD_IMAGE, config.PALWORLD_WINE_IMAGE):
        if not re.fullmatch(r"thijsvanloef/palworld-server-docker@sha256:[a-f0-9]{64}", image):
            raise RuntimeError("Palworld images must pin the approved repository by digest")
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
    inst = get_instance(server_id)
    if volume_key != "data":
        raise ValueError("Only the managed data directory is available")
    return checked(config.GAME_ROOT, data_name(inst))


def data_name(inst):
    name = inst.get("data_dir", inst["id"])
    if name != inst["id"] and not re.fullmatch(re.escape(inst["id"]) + r"-runtime-[a-f0-9]{12}", name):
        raise ValueError("Invalid instance data directory")
    return identifier(name)


def runtime(inst):
    value = inst.get("runtime", "native-linux")
    if value not in ("native-linux", "windows-wine"):
        raise ValueError("Unsupported runtime")
    return value


def image_for(inst):
    return config.PALWORLD_WINE_IMAGE if runtime(inst) == "windows-wine" else config.PALWORLD_IMAGE


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
    expected = str(Path(config.HOST_GAME_ROOT) / data_name(inst))
    if (
        len(mounts) != 1
        or mounts[0].get("Type") != "bind"
        or mounts[0].get("Source") != expected
        or mounts[0].get("Destination") != "/palworld"
    ):
        raise ValueError("Container mount verification failed")
    # Image digest and immutable Docker ID, not container names, establish ownership.
    if attrs.get("Config", {}).get("Image") != image_for(inst):
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
        if body.runtime == "windows-wine" and not body.acknowledge_code_mods:
            raise ValueError("Acknowledge third-party code execution before using the modded runtime")
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
            "runtime": body.runtime,
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
    return {
        k: v for k, v in inst.items() if k not in ("owner", "container_id", "settings", "previous_runtime")
    } | {
        "state": container_state(inst["id"]),
        "runtime": runtime(inst),
        "can_return_to_native": bool(inst.get("previous_runtime")),
    }


def _copy_saved(source_root, target_root, cancel=None):
    source = checked(source_root, "Pal/Saved")
    if not source.is_dir():
        return {"files": 0, "bytes": 0}
    paths = list(files(source))
    total = sum(path.stat().st_size for path in paths)
    if total > config.BACKUP_MAX_BYTES:
        raise ValueError("Saved data exceeds the conversion copy limit")
    if shutil.disk_usage(target_root).free < total + 64 * 1024**2:
        raise ValueError("Insufficient disk space for the separate runtime copy")
    destination = checked(target_root, "Pal/Saved")
    for path in paths:
        if cancel and cancel.is_set():
            raise TimeoutError("Runtime conversion cancelled")
        target = checked(destination, path.relative_to(source).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target, follow_symlinks=False)
    if os.geteuid() == 0:
        for path in [destination, *destination.rglob("*")]:
            os.chown(path, 1000, 1000, follow_symlinks=False)
    return {"files": len(paths), "bytes": total}


def prepare_converted_runtime(server_id, cancel=None):
    """Build a separate Windows data directory and keep the native one untouched."""
    with locked(server_id, allow_job=True):
        inst = get_instance(server_id)
        if runtime(inst) != "native-linux":
            raise ValueError("Only a native Linux instance can be converted")
        if inst.get("previous_runtime"):
            raise ValueError("This instance already retains a previous runtime")
        if not inst.get("installed"):
            raise ValueError("Install the native server before converting it")
        stop(server_id)
    from . import backups

    if cancel and cancel.is_set():
        raise TimeoutError("Runtime conversion cancelled")
    backups.recover(server_id)
    backup = backups.create_backup(server_id, manage_stop=False)
    inst = get_instance(server_id)
    old_name = data_name(inst)
    new_name = f"{inst['id']}-runtime-{secrets.token_hex(6)}"
    new_root = checked(config.GAME_ROOT, new_name)
    if new_root.exists():
        raise ValueError("Conversion target directory already exists")
    new_root.mkdir(mode=0o700)
    if os.geteuid() == 0:
        os.chown(new_root, 1000, 1000)
    try:
        copied = _copy_saved(volume_path(server_id), new_root, cancel)
        if cancel and cancel.is_set():
            raise TimeoutError("Runtime conversion cancelled")
        with locked(server_id, allow_job=True):
            inst = get_instance(server_id)
            if runtime(inst) != "native-linux" or data_name(inst) != old_name:
                raise ValueError("Runtime changed during conversion")
            remove_container(server_id)
            inst = get_instance(server_id)
            # The original files stay in place; only the recorded runtime moves.
            inst["previous_runtime"] = {
                "runtime": "native-linux",
                "data_dir": old_name,
                "backup": backup["filename"],
            }
            inst["runtime"] = "windows-wine"
            inst["data_dir"] = new_name
            inst["installed"] = False
            save(inst)
    except Exception:
        if get_instance(server_id).get("data_dir") != new_name and new_root.exists():
            shutil.rmtree(new_root)
        raise
    return {"backup": backup["filename"], **copied, "data_dir": new_name}


def rollback_runtime(server_id, confirmation):
    with locked(server_id):
        inst = get_instance(server_id)
        if confirmation != inst["name"]:
            raise ValueError("Type the server name to confirm the runtime change")
        previous = inst.get("previous_runtime")
        if not previous or previous.get("runtime") != "native-linux":
            raise ValueError("No previous native runtime is available")
        target = checked(config.GAME_ROOT, previous["data_dir"])
        if not target.is_dir():
            raise ValueError("The previous native runtime directory is missing")
        require_stopped(server_id)
        remove_container(server_id)
        inst = get_instance(server_id)
        inst["runtime"] = previous["runtime"]
        inst["data_dir"] = previous["data_dir"]
        inst["installed"] = True
        inst.pop("previous_runtime", None)
        save(inst)
        return {
            "status": "rolled-back",
            "runtime": inst["runtime"],
            "note": "The separate Windows installation is retained for inspection; the native files are unchanged.",
        }


def runtime_env(inst, setup=False):
    s = Settings.model_validate(inst["settings"])
    return {
        "PUID": "1000",
        "PGID": "1000",
        "SERVER_PLATFORM": "Windows" if runtime(inst) == "windows-wine" else "Linux",
        "PORT": "8211",
        "PLAYERS": str(s.players),
        "SERVER_NAME": s.server_name,
        "SERVER_DESCRIPTION": s.description,
        "ADMIN_PASSWORD": s.admin_password,
        "SERVER_PASSWORD": s.server_password,
        "COMMUNITY": "false",
        "RCON_ENABLED": "true",
        "RCON_PORT": "25575",
        # The pinned runtime saves and gracefully shuts down through its own REST API.
        # Only game UDP is published; this authenticated API stays on the game network.
        "REST_API_ENABLED": "true",
        "REST_API_PORT": "8212",
        "MOD_ENABLED": str(runtime(inst) == "windows-wine").lower(),
        "MOD_UPDATE_ON_BOOT": "false",
        "MOD_USE_PALDEFENDER": "false",
        "ENABLE_PLAYER_LOGGING": "false",
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
        image_for(inst),
        name=server_id,
        environment=runtime_env(inst, setup),
        ports={"8211/udp": (config.GAME_BIND_IP, inst["game_port"])},
        volumes={str(Path(config.HOST_GAME_ROOT) / data_name(inst)): {"bind": "/palworld", "mode": "rw"}},
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
    if runtime(inst) == "windows-wine":
        from . import code_mods

        code_mods.verify(server_id)
    else:
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
        result["game_process_running"] = any(
            any(name in " ".join(p) for name in ("PalServer-Linux", "PalServer-Win64")) for p in processes
        )
    except docker.errors.APIError:
        pass
    try:
        from .rest_helpers import game_info

        result["game_initialized"] = bool(game_info(server_id).get("version"))
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
        [sys.executable, "-m", "app.pull", image_for(get_instance(server_id))],
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
                windows = runtime(get_instance(server_id)) == "windows-wine"
                binary = checked(volume_path(server_id), "PalServer.exe" if windows else "PalServer.sh")
                if not binary.is_file():
                    raise ValueError("Installer exited without the expected server executable")
                break
        with locked(server_id, allow_job=True):
            if runtime(get_instance(server_id)) == "windows-wine":
                from . import code_mods

                job_log(server_id, "Verifying and preparing the pinned UE4SS loader.")
                code_mods.prepare_runtime(server_id, deadline=deadline, cancel=cancel)
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


def run_convert(server_id, cancel):
    try:
        job_log(server_id, "Stopping the native server and creating a verified world backup.")
        prepared = prepare_converted_runtime(server_id, cancel)
        job_log(
            server_id,
            f"Backup {prepared['backup']} verified; copied {prepared['files']} Saved files "
            "into a separate Windows installation.",
        )
        if cancel.is_set():
            raise TimeoutError("Runtime conversion cancelled")
        job_log(server_id, "Installing the Windows/Wine runtime and pinned UE4SS loader.")
        run_install(server_id, cancel, False)
    except Exception as exc:
        try:
            with locked(server_id, allow_job=True):
                stop(server_id)
        except Exception:
            job_log(server_id, "Could not confirm the game container stopped; inspect it before retrying.")
        job_save(
            server_id,
            state="cancelled" if cancel.is_set() else "error",
            error=str(exc)[:500],
            finished_at=time.time(),
        )


def begin_convert(server_id, confirmation, acknowledge):
    with locked(server_id):
        inst = get_instance(server_id)
        if confirmation != inst["name"]:
            raise ValueError("Type the server name to confirm the runtime change")
        if not acknowledge:
            raise ValueError("Acknowledge third-party code execution before using the modded runtime")
        if runtime(inst) != "native-linux":
            raise ValueError("Only a native Linux instance can be converted")
        if inst.get("previous_runtime"):
            raise ValueError("This instance already retains a previous runtime")
        if not inst.get("installed"):
            raise ValueError("Install the native server before converting it")
        inst["job"] = {
            "state": "running",
            "kind": "convert",
            "started_at": time.time(),
            "log": [],
            "error": "",
        }
        save(inst)
        cancel = threading.Event()
        _cancel[server_id] = cancel
        threading.Thread(target=run_convert, args=(server_id, cancel), daemon=True).start()
    return {
        "status": "queued",
        "note": "Native files are retained; conversion progress is reported separately.",
    }


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
