#!/usr/bin/env python3
"""Temporary labelled UI fixtures; refuse a running disposable game."""

import argparse
import io
import json
import secrets
import zipfile
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("operation", choices=["create", "remove"])
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / ".dev"
if root.is_symlink():
    raise SystemExit("Refusing linked development directory")
client = httpx.Client(base_url="http://127.0.0.1:18080", trust_env=False, timeout=60)
r = client.post(
    "/api/login", json={"username": "admin", "password": (root / "admin-password").read_text().strip()}
)
r.raise_for_status()
client.headers["x-csrf-token"] = r.json()["csrf"]
base = "/api/servers/gh-disposable-smoke"
r = client.get(base)
r.raise_for_status()
s = r.json()
if s["name"] != "disposable-smoke" or s["state"] not in ("exited", "created"):
    raise SystemExit("Disposable game must be stopped before using screenshot fixtures")
record = root / "screenshot-mods.json"
if args.operation == "remove":
    ids = json.loads(record.read_text()) if record.exists() else []
    for mid in reversed(ids):
        r = client.post(base + f"/mods/{mid}/actions", json={"action": "remove"})
        r.raise_for_status()
    record.unlink(missing_ok=True)
    print("Removed temporary screenshot packages; disposable game remains stopped.")
else:
    if record.exists():
        raise SystemExit("Remove previous screenshot fixtures first")
    ids = []

    def upload(name, asset, version, update="", dependencies=None):
        buf = io.BytesIO()
        meta = {
            "name": name,
            "description": "Screenshot fixture only. Not a playable mod; never booted.",
            "author": "Local demo",
            "version": version,
            "source": "Local screenshot fixture",
            "dependencies": dependencies or [],
        }
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(asset, b"synthetic UI asset" + b"\xe1\x12\x6f\x5a" + secrets.token_bytes(32))
            z.writestr("gamehub-mod.json", json.dumps(meta))
        r = client.post(
            base + "/mods/upload",
            content=buf.getvalue(),
            headers={
                "x-filename": "demo.zip",
                "x-update-id": update,
                "content-type": "application/octet-stream",
            },
        )
        r.raise_for_status()
        return r.json()

    first = upload("Nocturne assets (demo)", "Nocturne-demo.pak", "1.0")
    ids.append(first["id"])
    record.write_text(json.dumps(ids))
    upload("Nocturne assets (demo)", "Nocturne-demo.pak", "1.1", first["id"])
    r = client.post(
        base + f"/mods/{first['id']}/actions", json={"action": "enable", "acknowledge_unverified": True}
    )
    r.raise_for_status()
    second = upload("World details (demo)", "World-details-demo.pak", "0.8", dependencies=[first["id"]])
    ids.append(second["id"])
    record.write_text(json.dumps(ids))
    print("Created two labelled screenshot fixtures. Do not boot the game until removing them.")
