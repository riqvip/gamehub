"""Verified stopped-server Saved backups; bounded preview and atomic restore."""

import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from . import config
from . import docker_service as ds
from .archives import extract_zip, files
from .mods import sha
from .storage import atomic_json, checked, identifier, read_json


def directory(server_id):
    ds.get_instance(server_id)
    root = checked(config.BACKUP_DIR, identifier(server_id))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def list_backups(server_id):
    out = []
    for path in sorted(directory(server_id).glob("*.zip"), reverse=True):
        checked(path)
        meta = read_json(checked(directory(server_id), path.name + ".json"))
        if meta:
            out.append(
                {
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "created": meta["created"],
                    "sha256": meta["sha256"],
                    "verified": True,
                }
            )
    return sorted(out, key=lambda item: item["created"], reverse=True)


def create_backup(server_id, manage_stop=True):
    was_running = ds.container_state(server_id) == "running"
    if manage_stop:
        ds.stop(server_id)
    ds.require_stopped(server_id)
    container = ds.get_container(server_id)
    if container and (
        container.attrs.get("State", {}).get("OOMKilled")
        or container.attrs.get("State", {}).get("ExitCode") == 137
    ):
        raise ValueError(
            "The game was killed or ran out of memory. Inspect and recover the world before a consistent backup."
        )
    source = checked(ds.volume_path(server_id), "Pal/Saved")
    if not source.is_dir():
        raise ValueError("No Saved directory exists; no empty success backup was created")
    paths = list(files(source))
    total = sum(p.stat().st_size for p in paths)
    if not paths or total > config.BACKUP_MAX_BYTES or len(paths) > 100000:
        raise ValueError("Backup is empty or exceeds configured limits")
    destdir = directory(server_id)
    if shutil.disk_usage(destdir).free < total * 2 + 64 * 1024**2:
        raise ValueError("Insufficient backup disk space")
    name = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8] + ".zip"
    pending = destdir / (name + ".pending")
    dest = destdir / name
    try:
        hashes = {}
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path in paths:
                relative = path.relative_to(source).as_posix()
                hashes[relative] = sha(path)
                archive.write(path, arcname=relative)
        # CRC check is additional to the per-file SHA-256 verification on restore.
        with zipfile.ZipFile(pending) as archive:
            if archive.testzip() is not None:
                raise ValueError("Backup verification failed")
        digest = sha(pending)
        meta = {
            "server_id": server_id,
            "created": time.time(),
            "sha256": digest,
            "files": hashes,
            "extracted_bytes": total,
            "consistency": "server-stopped",
        }
        os.replace(pending, dest)
        atomic_json(destdir / (name + ".json"), meta)
        inst = ds.get_instance(server_id)
        inst["last_backup"] = time.time()
        ds.save(inst)
        # Retention runs only after a verified successful replacement backup.
        for old in list_backups(server_id)[inst["backup_policy"]["retain"] :]:
            delete_backup(server_id, old["filename"])
    finally:
        pending.unlink(missing_ok=True)
    if manage_stop and was_running:
        ds.start(server_id)
    return {"filename": name, "sha256": digest, "verified": True, "consistency": "server-stopped"}


def backup_paths(server_id, filename):
    if Path(filename).name != filename or not filename.endswith(".zip"):
        raise ValueError("Invalid backup filename")
    root = directory(server_id)
    archive = checked(root, filename)
    meta_path = checked(root, filename + ".json")
    meta = read_json(meta_path)
    if not archive.is_file() or not meta or meta.get("server_id") != server_id:
        raise KeyError("Backup not found")
    return archive, meta


def delete_backup(server_id, filename):
    archive, _ = backup_paths(server_id, filename)
    archive.unlink()
    archive.with_name(filename + ".json").unlink()
    return {"status": "deleted"}


def preview(server_id, filename):
    archive, meta = backup_paths(server_id, filename)
    if sha(archive) != meta["sha256"]:
        raise ValueError("Backup checksum mismatch")
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > 100000 or sum(i.file_size for i in z.infolist()) > config.BACKUP_MAX_BYTES:
            raise ValueError("Backup extraction limits exceeded")
        if set(z.namelist()) != set(meta["files"]):
            raise ValueError("Backup inventory mismatch")
    return {
        "filename": filename,
        "files": len(meta["files"]),
        "extracted_bytes": meta["extracted_bytes"],
        "destination": "Pal/Saved (this managed instance only)",
        "consistency": meta["consistency"],
        "requires_stopped": True,
        "note": "Existing Saved is retained as .gamehub-restore-old until the next restore.",
    }


def recover(server_id):
    pal = checked(ds.volume_path(server_id), "Pal")
    saved = checked(pal, "Saved")
    old = checked(pal, ".gamehub-restore-old")
    if not saved.exists() and old.exists():
        os.replace(old, saved)


def restore(server_id, filename, confirmation="", dry_run=True):
    summary = preview(server_id, filename)
    if dry_run:
        return summary
    inst = ds.get_instance(server_id)
    if confirmation != inst["name"]:
        raise ValueError("Type the server name to confirm restore")
    ds.require_stopped(server_id)
    recover(server_id)
    archive, meta = backup_paths(server_id, filename)
    pal = checked(ds.volume_path(server_id), "Pal")
    pal.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(pal).free < meta["extracted_bytes"] + 64 * 1024**2:
        raise ValueError("Insufficient disk space for restore staging")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=pal) as temp:
        stage = Path(temp) / "Saved"
        stage.mkdir()
        extract_zip(archive, stage, config.BACKUP_MAX_BYTES, 100000, time.monotonic() + 1800)
        found = {p.relative_to(stage).as_posix(): sha(p) for p in files(stage)}
        if found != meta["files"]:
            raise ValueError("Restored files failed integrity validation")
        # Only files from this archive and directories just created are re-owned.
        for path in [stage, *stage.rglob("*")]:
            if os.geteuid() == 0:
                os.chown(path, 1000, 1000, follow_symlinks=False)
        saved = checked(pal, "Saved")
        old = checked(pal, ".gamehub-restore-old")
        if old.exists():
            list(files(old))  # reject game-created links before deleting the previous recovery tree
            shutil.rmtree(old)
        if saved.exists():
            os.replace(saved, old)
        try:
            os.replace(stage, saved)
        except Exception:
            if old.exists():
                os.replace(old, saved)
            raise
    return {"status": "restored", "restart_required": True, "previous_saved_retained": True}


def schedule_tick():
    for inst in ds.list_instances():
        policy = inst.get("backup_policy", {})
        interval = policy.get("interval_hours", 0)
        if (
            interval
            and time.time() - inst.get("last_backup_attempt", inst.get("created_at", 0)) >= interval * 3600
        ):
            try:
                with ds.locked(inst["id"]):
                    inst = ds.get_instance(inst["id"])
                    inst["last_backup_attempt"] = time.time()
                    ds.save(inst)
                    create_backup(inst["id"])
                    atomic_json(
                        directory(inst["id"]) / "schedule-status.json", {"at": time.time(), "status": "ok"}
                    )
            except Exception as exc:
                atomic_json(
                    directory(inst["id"]) / "schedule-status.json",
                    {"at": time.time(), "status": "error", "error": str(exc)[:500]},
                )
