# Debian 13 deployment (operator-run; production authorization required)

This procedure is documentation, not an automatic installer. It does not establish
that a host with previous kernel/page-fault lockups is stable. Before authorizing
production, investigate storage, memory and kernel logs independently, verify
recoverable off-host backups, and complete the acceptance checklist in TESTING.md.
Never reboot, restart Docker globally, alter SSH/Tailscale/firewall rules, or clean
Docker resources as a GameHub recovery action.

## Prepare a new installation

Use an already installed Docker Engine and Compose v2 with `include` support
(Compose 2.20.3+). Prefer current supported packages from the
[official Debian Docker instructions](https://docs.docker.com/engine/install/debian/).
Verify `docker version`, `docker compose version`, available disk and RAM first.
The game image documents at least 16 GB RAM; reserve capacity for the host and
existing workloads on a 32 GB machine. Never allocate all RAM to Palworld.

Place this checkout at `/opt/stacks/gamehub` (or copy it there after review).
Create **new directories only**, and verify existing paths before changing ownership:

```text
/opt/stacks/gamehub/             compose.yaml, manager/, .env, secrets/
/opt/data/gamehub/database/      web sessions, activity log
/opt/data/gamehub/configuration/ controller instance records, mod revisions
/opt/data/gamehub/backups/       per-instance verified Saved archives
/opt/data/gamehub/logs/          optional exported logs; live logs use bounded Docker logging
/opt/data/palworld/gamehub/      new managed instances only
/opt/data/mc-servers/            never mounted, inspected or modified
```

On a clean target, the operator can create those new GameHub directories with
`install -d -m 0700 -o 1000 -g 1000 <each-new-path>`. Do not run recursive chown on
`/opt/data`, `/opt/data/palworld`, or an existing game directory. The `gamehub`
subdirectory deliberately avoids adopting existing Palworld saves.

```bash
cd /opt/stacks/gamehub
cp .env.example .env
# Edit .env: set DOCKER_GID from stat -c %g /var/run/docker.sock
# Review image digest, resource budget, hosts and binding addresses.
chmod 600 .env
# Build locally; no Python/uv installation on the host is required.
docker build -t gamehub-local:2 manager
# After creating the NEW secrets directory with UID/GID 1000 and mode 0700:
docker run --rm -it --network none --read-only --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --mount type=bind,src="$PWD/scripts/create-secrets.py",dst=/create-secrets.py,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/secrets \
  gamehub-local:2 python /create-secrets.py /secrets
```

The offline container prompts for your password twice and writes the hash and
controller token without printing them. It refuses to replace existing files.
Run secret generation as UID 1000 (as above), or arrange ownership of the **new individual
files** for UID 1000. Local Compose secrets are bind-mounted files: their host
permissions still apply. Both services run as UID 1000; the controller adds only
the socket group. Never loosen the socket to world-writable.

```bash
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d --wait
```

Do not run the legacy host installer. Its replacement exits without making changes.
No preexisting container is imported. The controller refuses existing instance
directories; use a separate authorized migration for existing Palworld data.

## HTTPS and Tailscale

Management defaults to `127.0.0.1:8000`, not all interfaces. `COOKIE_SECURE=true`
requires HTTPS. If Tailscale is already configured, an operator may explicitly
configure [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve) to proxy
its HTTPS hostname to `http://127.0.0.1:8000`. This repository never invokes Serve
or changes Tailscale itself. Add the exact HTTPS hostname to `ALLOWED_HOSTS`.
Trust only the verified immediate proxy peer if using `ADMIN_ALLOWED_IPS`; do not
blindly trust a whole private network. Docker NAT may change the peer address:
verify it in an isolated deployment before defining the allowlist.

Alternatively bind `MANAGER_BIND_IP` to the host's verified Tailscale address and
put an authenticated HTTPS reverse proxy in front. Do not bind management to
`0.0.0.0` by default. The controller has **no published port**. Never expose its
port, Docker socket, RCON or REST API to the internet.

Game access is configured separately: `GAME_BIND_IP` also defaults to loopback.
Choose the verified Tailscale interface for private players, or explicitly configure
game-only connectivity after review. Only each instance's UDP game port is published;
RCON is internal. Public community listing/query ports are disabled.

## Upgrades and shutdown

Back up web SQLite while the web service is stopped, controller configuration and
mod library while the controller is stopped, and verified world archives off-host.
Stop owned games before bringing the Compose services down; game containers are
created by the controller and are not Compose services. No pruning is required.
The game restart policy is `no`; installations never loop after a failure. Panel
services retry at most three times. After a host reboot, inspect the host and
explicitly start the desired game instances.

Rebuild the panel after reviewing a code update. Game **Update runtime** makes a
verified Saved backup before invoking the configured installation backend; it does
not change the operator's image digest. To replace the runtime digest itself, stop
all owned games, record their IDs and back up data, remove only the verified owned
stopped containers through a separately reviewed operator procedure, then update the
pin and restart the controller. Unrelated names/volumes must never be used as a shortcut.
