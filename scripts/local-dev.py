#!/usr/bin/env python3
"""Prepare a disposable local environment, confined to this checkout's .dev/."""

import os
import secrets
from pathlib import Path

from argon2 import PasswordHasher

repo = Path(__file__).resolve().parents[1]
root = repo / ".dev"
if root.exists():
    raise SystemExit(".dev already exists. Reuse its .env; this script will not overwrite it.")
root.mkdir(mode=0o700)
for sub in ("secrets", "gamehub/database", "gamehub/configuration", "gamehub/backups", "games"):
    (root / sub).mkdir(parents=True, mode=0o700)
password = secrets.token_urlsafe(24)
values = {
    "admin-password": password,
    "secrets/controller-token": secrets.token_urlsafe(32),
    "secrets/admin-password-hash": PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2).hash(
        password
    ),
}
for name, value in values.items():
    path = root / name
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
project = "gamehub-dev-" + secrets.token_hex(4)
(root / ".env").write_text(f"""COMPOSE_PROJECT_NAME={project}
GAMEHUB_DATA_ROOT={root}/gamehub
PALWORLD_DATA_ROOT={root}/games
GAMEHUB_SECRETS_ROOT={root}/secrets
MANAGER_BIND_IP=127.0.0.1
MANAGER_PORT=18080
DOCKER_GID={os.stat("/var/run/docker.sock").st_gid}
GAME_BIND_IP=127.0.0.1
GAME_MEMORY=4g
GAME_CPUS=2
COOKIE_SECURE=false
ALLOWED_HOSTS=localhost,127.0.0.1
PALWORLD_IMAGE=thijsvanloef/palworld-server-docker@sha256:07313feaecb42ecdea0b737ae922559dc5ab4c63d69275043f0943bd441fc35e
INSTALL_BACKEND=depotdownloader
INSTALL_TIMEOUT_SECONDS=900
""")
(root / ".env").chmod(0o600)
print("Disposable configuration created in .dev/.env; password is in .dev/admin-password.")
print("Start: docker compose --env-file .dev/.env -f compose.yaml up -d --build --wait")
print(
    "Stop:  docker compose --env-file .dev/.env -f compose.yaml down (stop owned game servers in the UI first)"
)
