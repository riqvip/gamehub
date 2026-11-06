#!/usr/bin/env python3
"""Create one disposable unrelated sentinel, verify rejection, remove only its ID."""

import secrets
from pathlib import Path

import docker
import httpx

root = Path(__file__).resolve().parents[1] / ".dev"
if root.is_symlink() or not (root / ".env").is_file():
    raise SystemExit("Disposable configuration missing")
settings = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line)
if not settings["COMPOSE_PROJECT_NAME"].startswith("gamehub-dev-"):
    raise SystemExit("Refusing a non-development project")
client = docker.from_env(timeout=10)
sid = "gh-unrelated-" + secrets.token_hex(5)
container = client.containers.create(
    "gamehub-local:2",
    name=sid,
    command=["python", "-c", "pass"],
    network_mode="none",
    read_only=True,
    cap_drop=["ALL"],
    security_opt=["no-new-privileges:true"],
    mem_limit="64m",
    pids_limit=16,
    labels={"io.gamehub.test": "isolation-sentinel"},
)
try:
    web = httpx.Client(base_url="http://127.0.0.1:18080", trust_env=False, timeout=10)
    r = web.post(
        "/api/login", json={"username": "admin", "password": (root / "admin-password").read_text().strip()}
    )
    r.raise_for_status()
    web.headers["x-csrf-token"] = r.json()["csrf"]
    for action in ("start", "stop", "restart", "remove"):
        r = web.post(f"/api/servers/{sid}/actions", json={"action": action, "confirmation": sid})
        if r.status_code != 404:
            raise RuntimeError(f"Unexpected response to unrelated operation: {r.status_code}")
    container.reload()
    if container.status != "created":
        raise RuntimeError("Unrelated sentinel state changed")
    print("PASS: real unrelated sentinel rejected for start/stop/restart/remove; Docker state unchanged")
finally:
    container.remove(force=False, v=False)
    client.close()
