"""Reviewed Wine code packages. Never execute an uploaded installer or accept arbitrary Lua."""

import copy
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from . import config, mods
from . import docker_service as ds
from .archives import copy_tree, extract_zip, files
from .downloads import download
from .storage import atomic_bytes, atomic_json, checked, read_json, relative

CATALOG = json.loads(Path(__file__).with_name("reviewed_mods.json").read_text())
LOADER_URL = "https://github.com/Okaetsu/RE-UE4SS/releases/download/2281fa31/UE4SS-Palworld-g2281fa31.zip"
LOADER_SHA = "f7543d57f8fdf5eab3731ac52121e6e7ff142fb3bfa17156e931037d0e44875b"
PWP_URL = (
    "https://codeload.github.com/Matraweber/PalWorkPriority/zip/dcc4811dc1117ef58a4f491d09c0513123ca0036"
)
PWP_SHA = "03f7e7ceaa9156b2029dc81a0d120debb2c34918fd89ea853f6c4ad2f252483a"
RELEASE_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "codeload.github.com"})
STATE = ".gamehub-code-state.json"
LOADER_STATE = ".gamehub-loader.json"
EVENTS = "code-events.json"
NOTE = (
    "Windows/Wine + UE4SS. Reviewed versions only; startup and lifecycle tested, "
    "actual expanded-base gameplay still needs validation. Players must install matching client mods and UE4SS."
)


def win64(sid):
    if ds.runtime(ds.get_instance(sid)) != "windows-wine":
        raise ValueError("Choose the modded Windows/Wine runtime first")
    return checked(ds.volume_path(sid), "Pal/Binaries/Win64")


def live_dir(sid):
    return checked(win64(sid), "ue4ss/Mods")


def cached_release(url, digest, deadline=None, cancel=None):
    root = checked(config.CONFIG_DIR, "runtime-cache")
    root.mkdir(exist_ok=True)
    target = checked(root, digest + ".zip")
    if target.exists() and mods.sha(target) == digest:
        return target
    with tempfile.TemporaryDirectory(dir=root, prefix="release-") as temp:
        pending = Path(temp) / "release.zip"
        download(url, pending, digest, allowed_hosts=RELEASE_HOSTS, deadline=deadline, cancel=cancel)
        os.replace(pending, target)
    return target


def prepare_runtime(sid, deadline=None, cancel=None):
    ds.require_stopped(sid)
    base = win64(sid)
    root = checked(base, "ue4ss")
    if checked(root, LOADER_STATE).is_file():
        verify(sid)
        return
    if root.exists():
        raise ValueError("Existing unmanaged UE4SS directory will not be adopted")
    archive = cached_release(LOADER_URL, LOADER_SHA, deadline, cancel)
    with tempfile.TemporaryDirectory(dir=config.CONFIG_DIR, prefix="loader-") as temp:
        stage = Path(temp)
        extract_zip(archive, stage, 128 * 1024**2, 2048, deadline or time.monotonic() + 60)
        pending = checked(base, ".gamehub-loader-next")
        if pending.exists():
            list(files(pending))
            shutil.rmtree(pending)
        copy_tree(stage / "ue4ss", pending)
        # Only the shared helpers are required. Disable bundled example/console mods.
        shared = stage / "ue4ss/Mods/shared"
        shutil.rmtree(pending / "Mods")
        (pending / "Mods").mkdir()
        copy_tree(shared, pending / "Mods/shared")
        (pending / "Mods/mods.txt").write_text("")
        atomic_json(pending / "Mods" / STATE, mods.signed(sid, {"mods": []}))
        immutable = {
            p.relative_to(pending).as_posix(): mods.sha(p)
            for p in files(pending)
            if p.relative_to(pending).parts[0] != "Mods"
        }
        immutable.update(
            {p.relative_to(pending).as_posix(): mods.sha(p) for p in files(pending / "Mods/shared")}
        )
        marker = {"release": LOADER_SHA, "files": immutable, "proxy_sha256": mods.sha(stage / "dwmapi.dll")}
        atomic_json(pending / LOADER_STATE, mods.signed(sid, marker))
        proxy = checked(base, "dwmapi.dll")
        if proxy.exists() and mods.sha(proxy) != marker["proxy_sha256"]:
            raise ValueError("Unmanaged loader proxy DLL will not be overwritten")
        atomic_bytes(proxy, (stage / "dwmapi.dll").read_bytes())
        os.replace(pending, root)
    verify(sid)


def recover(sid):
    ds.require_stopped(sid)
    live = live_dir(sid)
    old = checked(live.parent, ".gamehub-code-old")
    pending = checked(live.parent, ".gamehub-code-next")
    if old.exists():
        if not live.exists():
            os.replace(old, live)
        else:
            if not checked(live, STATE).is_file():
                raise ValueError("Interrupted code-mod transaction requires inspection")
            mods.read_state(sid, live / STATE)
            list(files(old))
            shutil.rmtree(old)
    if pending.exists():
        list(files(pending))
        shutil.rmtree(pending)


def state(sid):
    live = live_dir(sid)
    if not checked(live, STATE).is_file():
        raise ValueError("Install the modded runtime first; UE4SS has not been prepared")
    return mods.read_state(sid, live / STATE)


def events(sid, message):
    path = checked(mods.library(sid), EVENTS)
    history = read_json(path, [])[-99:]
    atomic_json(path, history + [{"at": time.time(), "message": message[:500]}])


def order(manifest):
    return "".join(
        m["package"] + " : 1\n"
        for m in sorted(manifest["mods"], key=lambda m: m["package"], reverse=True)
        if m["enabled"]
    )


def verify(sid):
    ds.require_stopped(sid)
    recover(sid)
    root = checked(win64(sid), "ue4ss")
    marker_path = checked(root, LOADER_STATE)
    if not marker_path.is_file():
        raise ValueError("Pinned UE4SS loader is missing; install/update the runtime first")
    marker = mods.read_state(sid, marker_path)
    if (
        marker.get("release") != LOADER_SHA
        or mods.sha(checked(win64(sid), "dwmapi.dll")) != marker["proxy_sha256"]
    ):
        raise ValueError("Loader integrity check failed")
    for name, digest in marker["files"].items():
        if mods.sha(checked(root, name)) != digest:
            raise ValueError("Loader integrity check failed: " + name)
    manifest = state(sid)
    live = live_dir(sid)
    expected = {"shared", "mods.txt", STATE} | {m["package"] for m in manifest["mods"]}
    if any(p.name not in expected for p in live.iterdir()):
        raise ValueError("Unmanaged code mod files detected; refusing startup")
    if checked(live, "mods.txt").read_text() != order(manifest):
        raise ValueError("Code mod enable state was changed outside GameHub")
    for mod in manifest["mods"]:
        spec = CATALOG.get(mod["package"])
        if not spec or mod["version"] != spec["version"]:
            raise ValueError("Code mod version is not reviewed")
        folder = checked(live, mod["package"])
        if checked(folder, "enabled.txt").exists():
            raise ValueError("Unexpected enable marker; manage code mods through GameHub")
        scripts = checked(folder, "Scripts")
        actual = {p.relative_to(scripts).as_posix(): mods.sha(p) for p in files(scripts)}
        if actual != spec["scripts"]:
            raise ValueError("Reviewed code mod scripts failed integrity verification")
    return manifest


def commit(sid, manifest, addition=None):
    verify(sid)
    live = live_dir(sid)
    pending = checked(live.parent, ".gamehub-code-next")
    old = checked(live.parent, ".gamehub-code-old")
    paths = list(files(live))
    if len(paths) > 20000 or sum(p.stat().st_size for p in paths) > config.MAX_EXTRACTED:
        raise ValueError("Code mod data exceeds transaction limits")
    try:
        copy_tree(live, pending)
        keep = {m["package"] for m in manifest["mods"]}
        for folder in pending.iterdir():
            if folder.is_dir() and folder.name != "shared" and folder.name not in keep:
                shutil.rmtree(folder)
        if addition:
            name, source = addition
            copy_tree(source, pending / name / "Scripts")
        atomic_bytes(pending / "mods.txt", order(manifest).encode())
        atomic_json(pending / STATE, mods.signed(sid, manifest))
        os.replace(live, old)
        try:
            os.replace(pending, live)
        except Exception:
            os.replace(old, live)
            raise
        shutil.rmtree(old)
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def list_mods(sid):
    inst = ds.get_instance(sid)
    current = ds.runtime(inst)
    events = read_json(checked(mods.library(sid), EVENTS), [])
    catalog = [
        {"package": k, **{x: v[x] for x in ("name", "version", "description", "source")}}
        for k, v in CATALOG.items()
    ]
    result = {
        "installed": [],
        "events": events,
        "compatibility_note": NOTE,
        "runtime": current,
        "available": current == "windows-wine",
        "loader_ready": False,
        "restart_required": True,
        "catalog": catalog,
    }
    if current != "windows-wine":
        result["compatibility_note"] = (
            "Reviewed code mods require the separate Windows/Wine runtime. "
            "Switch the stopped server to that runtime first; native files stay untouched."
        )
        return result
    live = live_dir(sid)
    if not checked(live, STATE).is_file():
        result["compatibility_note"] = "Install the Windows/Wine runtime to prepare the pinned UE4SS loader."
        return result
    if ds.container_state(sid) != "running":
        recover(sid)
    manifest = state(sid)
    result.update(installed=manifest["mods"], loader_ready=True)
    return result


def install(sid, source, filename, update_id="", source_label="local upload"):
    ds.require_stopped(sid)
    relative(filename)
    if "/" in filename or not filename.lower().endswith(".zip"):
        raise ValueError("Code mods require ZIP. Convert RAR to ZIP without changing the files.")
    if source.stat().st_size > config.MAX_UPLOAD:
        raise ValueError("Upload size limit exceeded")
    manifest = verify(sid)
    if update_id:
        raise ValueError(
            "Only the current reviewed versions are available; no newer reviewed update is installed"
        )
    with tempfile.TemporaryDirectory(dir=config.CONFIG_DIR, prefix="code-upload-") as temp:
        stage = Path(temp)
        extract_zip(source, stage, config.MAX_EXTRACTED, config.MAX_FILES, time.monotonic() + 60)
        matches = []
        for main in files(stage):
            if main.name != "main.lua" or main.parent.name != "Scripts":
                continue
            actual = {p.relative_to(main.parent).as_posix(): mods.sha(p) for p in files(main.parent)}
            for name, spec in CATALOG.items():
                if actual == spec["scripts"]:
                    matches.append((name, main.parent))
        if len(matches) != 1:
            raise ValueError(
                "Upload the complete reviewed Base Radius Improved 1.2.2 or Pal Work Priority 0.5.0 ZIP; scripts do not match"
            )
        name, scripts = matches[0]
        if any(m["package"] == name for m in manifest["mods"]):
            raise ValueError("This reviewed version is already installed")
        spec = CATALOG[name]
        mid = "mod-" + uuid.uuid4().hex[:16]
        revision = "rev-" + uuid.uuid4().hex
        stored = checked(mods.library(sid), f"{mid}/{revision}")
        copy_tree(scripts, stored)
        mod = {
            **{k: spec[k] for k in ("name", "version", "description", "author", "source")},
            "id": mid,
            "package": name,
            "revision": revision,
            "enabled": False,
            "kind": "reviewed-code",
            "installed_at": time.time(),
            "sha256": mods.sha(source),
            "dependencies": ["UE4SS 2281fa31 (managed)"],
            "files": [{"name": "Scripts/" + p, "sha256": digest} for p, digest in spec["scripts"].items()],
            "compatibility": "Windows/Wine startup tested; client gameplay verification required",
            "update_available": None,
            "previous": None,
            "installation_error": "",
        }
        manifest["mods"].append(mod)
        commit(sid, manifest, (name, stored))
    events(sid, f"Installed reviewed {name} {spec['version']} disabled; matching client mods required.")
    return mod


def install_pwp(sid):
    ds.require_stopped(sid)
    win64(sid)
    archive = cached_release(PWP_URL, PWP_SHA)
    return install(sid, archive, "PalWorkPriority.zip")


def action(sid, mid, operation, acknowledge=False):
    ds.require_stopped(sid)
    manifest = copy.deepcopy(verify(sid))
    mod = next((m for m in manifest["mods"] if m["id"] == mid), None)
    if not mod:
        raise KeyError("Mod not found")
    if operation == "enable":
        if not acknowledge:
            raise ValueError("Acknowledge code execution and matching client requirements before enabling")
        mod["enabled"] = True
    elif operation == "disable":
        mod["enabled"] = False
    elif operation == "remove":
        if mod["enabled"]:
            raise ValueError(
                "Disable the mod before removal. For PWP restore its work permissions in-game first."
            )
        manifest["mods"].remove(mod)
    else:
        raise ValueError("No previous reviewed update is available")
    commit(sid, manifest)
    events(sid, f"{operation}: {mod['name']}; start the server to apply.")
    return {"status": operation, "restart_required": True}
