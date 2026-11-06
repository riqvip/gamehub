# GameHub

A private, self-hosted Palworld control room: lifecycle management, logs and RCON,
versioned asset-mod packages, verified backups, and a responsive dark interface.
Python/FastAPI + vanilla JavaScript; Docker Compose is the supported deployment.

**Development hardening release; not certified production-ready.** Read
[TESTING.md](TESTING.md) for observed results and remaining acceptance criteria.
This fork intentionally disables generic images, Dockerfile builds, anonymous
status pages, and other game templates until they have reviewed controller
policies. It does not discover or adopt existing Docker workloads.

## Architecture

- **Web**: UID 1000, read-only filesystem, session database only; no Docker socket,
  game mounts, or backup mounts. Argon2id login, HttpOnly cookies, CSRF tokens,
  session expiration/revocation and an activity log.
- **Controller**: private authenticated capability API, UID 1000 plus the Docker
  socket group. Owns instance records, mod revisions and backups. The socket
  still grants root-equivalent host authority: this is a sensitive component.
- **Game instances**: fixed digest-pinned native Linux image, fixed per-instance
  data root, non-root user, dropped capabilities, bounded CPU/RAM/PIDs, no automatic
  restart loop. Only the game UDP port is published, to loopback by default.

## Local development

Use a disposable checkout and an existing Docker installation. No script installs
host packages or changes the firewall, SSH, Tailscale or Docker daemon.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python scripts/local-dev.py
docker compose --env-file .dev/.env -f compose.yaml up -d --build --wait
```

Open `http://127.0.0.1:18080`. The generated local password is in
`.dev/admin-password`; do not share or commit it. Local configuration sets
`COOKIE_SECURE=false` only for this isolated HTTP test. Production requires HTTPS.

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/docker-smoke.py
# Explicitly download the disposable game runtime, with a 15-minute deadline:
.venv/bin/python scripts/docker-smoke.py --install
```

Stop owned game instances in the UI before `docker compose --env-file .dev/.env
-f compose.yaml down`. Runtime-created game containers are deliberately outside
Compose's service lifecycle. Data is retained; no volume removal or prune is needed.

[View all 16 screenshots](docs/screenshots/index.html) — actual desktop/mobile UI, including demo mod-library entries and restore preview.

## Guides

[Security and threat model](SECURITY.md) · [Audit](AUDIT.md) ·
[Deployment](DEPLOYMENT.md) · [Palworld](PALWORLD.md) · [Mods](MODDING.md) ·
[Backup and recovery](BACKUPS.md) · [Validation](TESTING.md)

No production deployment is performed by this repository. Existing Minecraft and
Palworld files require a separately planned, explicitly authorized migration.
MIT licensed; unofficial and unaffiliated with Pocketpair or the runtime authors.
