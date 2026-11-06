#!/usr/bin/env python3
"""Exercise only the disposable .dev Compose deployment. Never accepts production URLs."""

import argparse
import json
import secrets
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument(
    "--install", action="store_true", help="Download Palworld in the disposable dev environment"
)
parser.add_argument("--check", action="store_true", help="Report existing instance and bounded log output")
parser.add_argument(
    "--update", action="store_true", help="Run a controlled update of the installed disposable runtime"
)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
root = repo / ".dev"
if not root.is_dir() or root.is_symlink():
    raise SystemExit("Run local-dev.py first")
settings = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line)
if not (settings["COMPOSE_PROJECT_NAME"].startswith("gamehub-dev-")):
    raise RuntimeError("Smoke-test expectation failed")
if not (Path(settings["PALWORLD_DATA_ROOT"]) == root / "games"):
    raise RuntimeError("Smoke-test expectation failed")
client = httpx.Client(base_url="http://127.0.0.1:18080", timeout=180, trust_env=False)
response = client.post(
    "/api/login", json={"username": "admin", "password": (root / "admin-password").read_text().strip()}
)
response.raise_for_status()
client.headers["x-csrf-token"] = response.json()["csrf"]


def request(method, path, **kwargs):
    r = client.request(method, "/api/" + path, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r.json()


servers = request("GET", "servers")
if not servers:
    if not (not args.check):
        raise RuntimeError("Smoke-test expectation failed")
    s = request(
        "POST",
        "servers",
        json={
            "name": "disposable-smoke",
            "game_port": 18211,
            "settings": {
                "admin_password": secrets.token_urlsafe(24),
                "server_name": "Disposable GameHub test",
                "players": 2,
            },
        },
    )
else:
    if not (len(servers) == 1 and servers[0]["name"] == "disposable-smoke"):
        raise RuntimeError("Smoke-test expectation failed")
    s = servers[0]
sid = s["id"]
base = "servers/" + sid
if args.check:
    print(json.dumps(request("GET", base), indent=2))
    print(request("GET", base + "/logs")["logs"][-8000:])
    raise SystemExit(0)
if not (client.get("/api/activity").status_code == 200):
    raise RuntimeError("Smoke-test expectation failed")
if not (httpx.get("http://127.0.0.1:18080/api/servers", trust_env=False).status_code == 401):
    raise RuntimeError("Smoke-test expectation failed")
if not (
    client.post(
        "/api/servers/" + sid + "/actions", headers={"x-csrf-token": "bad"}, json={"action": "start"}
    ).status_code
    == 403
):
    raise RuntimeError("Smoke-test expectation failed")
if not (
    client.post("/api/servers/" + sid + "/build", json={"dockerfile": "FROM scratch"}).status_code == 404
):
    raise RuntimeError("Smoke-test expectation failed")
print("PASS: login, session, CSRF, removed Docker-build capability, isolated registration", flush=True)
if args.install or args.update:
    if args.update:
        if not s["installed"]:
            raise RuntimeError("Install the disposable server before updating it")
        request("POST", base + "/actions", json={"action": "update"})
    if not s["installed"] and s.get("job", {}).get("state") != "running":
        request("POST", base + "/actions", json={"action": "install"})
    deadline = time.monotonic() + 960
    previous = ""
    while time.monotonic() < deadline:
        s = request("GET", base)
        job = s.get("job", {})
        current = job.get("state", "")
        progress = request("GET", base + "/logs")["logs"][-500:]
        if progress != previous:
            print(f"INSTALL {current}: {progress}", flush=True)
            previous = progress
        if current in ("error", "cancelled", "interrupted"):
            raise SystemExit("Installation did not complete: " + job.get("error", ""))
        if current == "done":
            break
        time.sleep(5)
    else:
        request("POST", base + "/actions", json={"action": "cancel"})
        raise SystemExit("Timed out; cancellation requested")
    print(
        "PASS: controlled Palworld update" if args.update else "PASS: setup-only Palworld installation",
        flush=True,
    )
else:
    print("Use --install for the bounded Palworld installation test.", flush=True)
