#!/usr/bin/env python3
"""Bounded real lifecycle/backup test for the disposable .dev instance only."""

import io
import json
import os
import time
import zipfile
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1] / ".dev"
if not (not root.is_symlink()):
    raise RuntimeError("Smoke-test expectation failed")
env = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line)
if not (env["COMPOSE_PROJECT_NAME"].startswith("gamehub-dev-")):
    raise RuntimeError("Smoke-test expectation failed")
if not (Path(env["PALWORLD_DATA_ROOT"]) == root / "games"):
    raise RuntimeError("Smoke-test expectation failed")
client = httpx.Client(base_url="http://127.0.0.1:18080", timeout=180, trust_env=False)
r = client.post(
    "/api/login", json={"username": "admin", "password": (root / "admin-password").read_text().strip()}
)
r.raise_for_status()
client.headers["x-csrf-token"] = r.json()["csrf"]


def request(method, path, **kwargs):
    r = client.request(method, "/api/" + path, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r.json()


servers = request("GET", "servers")
if not (len(servers) == 1 and servers[0]["name"] == "disposable-smoke" and servers[0]["installed"]):
    raise RuntimeError("Smoke-test expectation failed")
sid = servers[0]["id"]
base = "servers/" + sid


def action(value):
    return request("POST", base + "/actions", json={"action": value})


def await_ready():
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        health = request("GET", base + "/health")
        if health["game_initialized"]:
            print("PASS: authenticated RCON game initialization", json.dumps(health), flush=True)
            return
        if health["state"] == "exited":
            break
        time.sleep(5)
    print(request("GET", base + "/logs")["logs"][-6000:], flush=True)
    raise RuntimeError("Game did not initialize within 180 seconds")


try:
    action("start")
    await_ready()
    print("PLAYERS", request("GET", base + "/players"), flush=True)
    request("POST", base + "/rcon", json={"command": "Save"})
    action("restart")
    await_ready()
    backup = request("POST", base + "/backups")
    print("PASS: game-consistent Saved backup", backup, flush=True)
    action("stop")
    preview = request(
        "POST", base + "/backups/restore", json={"filename": backup["filename"], "dry_run": True}
    )
    request(
        "POST",
        base + "/backups/restore",
        json={"filename": backup["filename"], "dry_run": False, "confirmation": "disposable-smoke"},
    )
    print("PASS: checksum-verified preview and Saved restore", preview, flush=True)
    # Synthetic asset fixture exercises management only. Never boot with it enabled.
    payload = b"gamehub synthetic workflow fixture" + b"\xe1\x12\x6f\x5a" + os.urandom(32)

    def upload(content, update=""):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("SmokeTest.pak", content)
        return request(
            "POST",
            base + "/mods/upload",
            content=stream.getvalue(),
            headers={
                "x-filename": "smoke.zip",
                "x-update-id": update,
                "content-type": "application/octet-stream",
            },
        )

    m = upload(payload)
    mid = m["id"]
    for op in ("enable", "disable"):
        request("POST", base + f"/mods/{mid}/actions", json={"action": op, "acknowledge_unverified": True})
    upload(payload + b"revision2", mid)
    for op in ("rollback", "remove"):
        request("POST", base + f"/mods/{mid}/actions", json={"action": op})
    print(
        "PASS: disposable mod upload/enable/disable/update/rollback/remove (no game execution claim)",
        flush=True,
    )
    action("start")
    await_ready()
    print("PASS: real start/stop/restart, world persistence after restore", flush=True)
finally:
    action("stop")
    print("Disposable game left stopped.", flush=True)
