"""Versioned asset packages and stopped-server directory transactions.

Native Linux compatibility is UNVERIFIED. Never load code or execute installers.
"""

import copy
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from . import config
from . import docker_service as ds
from .archives import extract_zip, files
from .models import ModMetadata
from .storage import atomic_json, checked, identifier, read_json, relative

STATE = ".gamehub-state.json"


def library(server_id):
    ds.get_instance(server_id)
    root = checked(config.CONFIG_DIR, f"mods/{identifier(server_id)}")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def mods_dir(server_id, create=True):
    base = ds.volume_path(server_id)
    paks = checked(base, "Pal/Content/Paks")
    if create:
        paks.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            for path in (paks, paks.parent, paks.parent.parent):
                os.chown(path, 1000, 1000)
    return checked(paks, "~mods")


def signed(server_id, manifest):
    value = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(ds.get_instance(server_id)["owner"].encode(), value, "sha256").hexdigest()
    return {"state": manifest, "signature": signature}


def read_state(server_id, path):
    data = read_json(checked(path))
    if data is None:
        return {"mods": []}
    if not isinstance(data, dict) or not isinstance(data.get("state"), dict):
        raise ValueError("Mod state integrity verification failed")
    signature = signed(server_id, data["state"])["signature"]
    if not hmac.compare_digest(str(data.get("signature", "")), signature):
        raise ValueError("Mod state integrity verification failed")
    return data["state"]


def recover(server_id):
    ds.require_stopped(server_id)
    live = mods_dir(server_id)
    old = checked(live.parent, ".gamehub-mods-old")
    pending = checked(live.parent, ".gamehub-mods-next")
    # The new tree contains its own manifest: switching files and state is one commit.
    if old.exists():
        if not live.exists():
            os.replace(old, live)
        else:
            if not checked(live, STATE).is_file():
                raise ValueError("Interrupted mod transaction needs operator inspection")
            read_state(server_id, live / STATE)
            shutil.rmtree(old)
    if pending.exists():
        shutil.rmtree(pending)


def state(server_id):
    recover(server_id)
    live = mods_dir(server_id)
    if live.exists() and not checked(live, STATE).is_file():
        raise ValueError("Existing unmanaged ~mods directory will not be adopted")
    return read_state(server_id, checked(live, STATE))


def events(server_id, message):
    path = checked(library(server_id), "events.json")
    history = read_json(path, [])[-99:]
    atomic_json(path, history + [{"at": time.time(), "message": message[:500]}])


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def verify_asset(path):
    suffix = path.suffix.lower()
    size = path.stat().st_size
    if size == 0:
        raise ValueError("Empty mod file")
    with path.open("rb") as f:
        start = f.read(32)
        if start.startswith((b"MZ", b"\x7fELF", b"#!")):
            raise ValueError("Executable content is unsupported")
        if suffix == ".pak":
            f.seek(max(0, size - 65536))
            if b"\xe1\x12\x6f\x5a" not in f.read():
                raise ValueError("Invalid Unreal PAK footer")
        elif suffix == ".utoc":
            if not start.startswith(b"-==--==--==--==-"):
                raise ValueError("Invalid Unreal TOC header")
        elif suffix == ".ini":
            if size > 1024 * 1024 or b"\x00" in path.read_bytes():
                raise ValueError("Invalid mod configuration file")
            path.read_text(encoding="utf-8")
        elif suffix != ".ucas":
            raise ValueError(
                f"Unsupported mod type: {suffix or '(no extension)'}. DLL, Lua, loaders and scripts are not supported."
            )


def commit(server_id, manifest):
    ds.require_stopped(server_id)
    live = mods_dir(server_id)
    pending = checked(live.parent, ".gamehub-mods-next")
    old = checked(live.parent, ".gamehub-mods-old")
    recover(server_id)
    pending.mkdir()
    names = set()
    enabled = {m["id"] for m in manifest["mods"] if m["enabled"]}
    try:
        for mod in manifest["mods"]:
            if not mod["enabled"]:
                continue
            if any(dep not in enabled for dep in mod["dependencies"]):
                raise ValueError("Enable required dependency packages first")
            revision = checked(library(server_id), f"{identifier(mod['id'])}/{identifier(mod['revision'])}")
            for entry in mod["files"]:
                name = entry["name"]
                relative(name)
                if "/" in name or name.casefold() in names:
                    raise ValueError("Conflicting mod filenames; no files were changed")
                names.add(name.casefold())
                source = checked(revision, name)
                if sha(source) != entry["sha256"]:
                    raise ValueError("Stored mod revision failed integrity verification")
                shutil.copyfile(source, pending / name, follow_symlinks=False)
        atomic_json(pending / STATE, signed(server_id, manifest))
        # All files readable by the non-root game process; controller retains ownership.
        for path in pending.iterdir():
            path.chmod(0o644)
        pending.chmod(0o755)
        if live.exists():
            os.replace(live, old)
        try:
            os.replace(pending, live)
        except Exception:
            if old.exists():
                os.replace(old, live)
            raise
        if old.exists():
            shutil.rmtree(old)
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def list_mods(server_id):
    # Read only while running; recovery/mutation is allowed only after stopping.
    if ds.container_state(server_id) == "running":
        live = mods_dir(server_id, create=False)
        manifest = read_state(server_id, checked(live, STATE))
    else:
        manifest = state(server_id)
    return {
        "installed": manifest["mods"],
        "events": read_json(library(server_id) / "events.json", []),
        "compatibility_note": (
            "Asset staging only: the current runtime disables game mod loading. "
            "UE4SS, Lua and Workshop code mods require a separate runtime and are unsupported here."
        ),
        "nexus_url": "https://www.nexusmods.com/palworld",
        "restart_required": True,
    }


def install(server_id, source: Path, filename: str, update_id="", source_label="local upload"):
    ds.require_stopped(server_id)
    relative(filename)
    if "/" in filename or len(filename) > 180 or source.stat().st_size > config.MAX_UPLOAD:
        raise ValueError("Invalid filename or upload too large")
    manifest = state(server_id)
    if len(manifest["mods"]) >= 100 and not update_id:
        raise ValueError("Maximum 100 installed mod packages")
    if shutil.disk_usage(library(server_id)).free < config.MAX_EXTRACTED * 2:
        raise ValueError("Insufficient staging disk space")
    old = next((m for m in manifest["mods"] if m["id"] == update_id), None)
    if update_id and not old:
        raise KeyError("Mod to update not found")
    package_hash = sha(source)
    if any(m["sha256"] == package_hash for m in manifest["mods"]):
        raise ValueError("This package is already installed")
    mod_id = old["id"] if old else "mod-" + uuid.uuid4().hex[:16]
    revision = "rev-" + uuid.uuid4().hex
    revision_path = checked(library(server_id), f"{mod_id}/{revision}")
    revision_path.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix="mod-", dir=library(server_id)) as temp:
            stage = Path(temp)
            if filename.lower().endswith(".zip"):
                extract_zip(source, stage, config.MAX_EXTRACTED, config.MAX_FILES, time.monotonic() + 60)
            else:
                shutil.copyfile(source, stage / filename)
            meta = ModMetadata(name=Path(filename).stem, source=source_label)
            entries, names = [], set()
            for path in files(stage):
                if path.name == "gamehub-mod.json":
                    if path.stat().st_size > 16384:
                        raise ValueError("Mod metadata too large")
                    meta = ModMetadata.model_validate_json(path.read_bytes())
                    continue
                if path.name.lower() in ("readme.txt", "license.txt", "readme.md"):
                    continue
                verify_asset(path)
                name = path.name
                if name.casefold() in names:
                    raise ValueError("Duplicate mod filename")
                names.add(name.casefold())
                shutil.copyfile(path, revision_path / name, follow_symlinks=False)
                entries.append({"name": name, "sha256": sha(path), "size_bytes": path.stat().st_size})
            if not entries or not any(Path(e["name"]).suffix.lower() in (".pak", ".utoc") for e in entries):
                raise ValueError(
                    "Package must contain Unreal assets; configuration-only installs are unsupported"
                )
            for e in entries:
                stem, ext = Path(e["name"]).stem.casefold(), Path(e["name"]).suffix.lower()
                if ext in (".ucas", ".utoc") and stem + (".utoc" if ext == ".ucas" else ".ucas") not in names:
                    raise ValueError("IoStore .utoc and .ucas companions must be installed together")
            for dep in meta.dependencies:
                identifier(dep)
                if not any(m["id"] == dep for m in manifest["mods"]):
                    raise ValueError(f"Missing dependency package: {dep}")
            mod = {
                **meta.model_dump(),
                "id": mod_id,
                "revision": revision,
                "files": entries,
                "sha256": package_hash,
                "enabled": old["enabled"] if old else False,
                "installed_at": time.time(),
                "compatibility": "unverified-linux",
                "update_available": None,
                "installation_error": "",
                "previous": old if old else None,
            }
            manifest["mods"] = [m for m in manifest["mods"] if m["id"] != mod_id] + [mod]
            commit(server_id, manifest)
        events(server_id, f"Installed {mod_id}; assets validated, runtime compatibility unverified.")
        return mod
    except Exception as exc:
        # A failure after publication (e.g. event log I/O) must never delete live revision files.
        published = read_state(server_id, checked(mods_dir(server_id), STATE))
        if not any(m["revision"] == revision for m in published["mods"]):
            shutil.rmtree(revision_path)
            events(server_id, f"Installation rejected: {str(exc)[:400]}")
        raise


def action(server_id, mod_id, action, acknowledge=False):
    ds.require_stopped(server_id)
    manifest = state(server_id)
    mod = next((m for m in manifest["mods"] if m["id"] == mod_id), None)
    if mod is None:
        raise KeyError("Mod not found")
    if action == "enable":
        if not acknowledge:
            raise ValueError("Acknowledge unverified native Linux compatibility before enabling")
        mod["enabled"] = True
    elif action == "disable":
        mod["enabled"] = False
    elif action == "remove":
        if any(mod_id in m["dependencies"] for m in manifest["mods"] if m["id"] != mod_id):
            raise ValueError("Another installed mod depends on this package")
        manifest["mods"].remove(mod)
    elif action == "rollback":
        if not mod.get("previous"):
            raise ValueError("No previous revision available")
        previous = copy.deepcopy(mod["previous"])
        previous["enabled"] = mod["enabled"]
        manifest["mods"] = [previous if m["id"] == mod_id else m for m in manifest["mods"]]
    else:
        raise ValueError("Unknown mod operation")
    commit(server_id, manifest)
    events(server_id, f"{action}: {mod_id}; restart required to apply.")
    return {"status": action, "restart_required": True}
