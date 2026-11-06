# Validation and acceptance status

Validation date: 2026-11-05 (America/Los_Angeles). These results describe the local
WSL development environment, not `homeserver`. No production deployment, host-service
change, Minecraft-data access or Docker cleanup was performed.

## Reproduce automated checks

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
bash scripts/check.sh
```

**93 automated tests passed.**

The suite exercises authentication, session expiry/revocation, CSRF, throttling,
CORS/Origin and security headers, proxy trust chains, controller authentication,
forbidden Docker capabilities, ownership/mount checks, malicious archives, links,
ZIP bombs, CRC/size/file-count limits, SSRF redirects/private DNS, SHA-256 downloads,
mod conflicts/dependencies/enable/disable/update/rollback, failed directory publication,
configuration injection, backup/restore confirmation/checksums/retention, forced-kill
handling, lifecycle state, initialization reporting, bounded install failure and cancellation.
Docker is mocked for unit tests; all files are disposable pytest data.

The subsequent [requested mod investigation](docs/palworld-mod-investigation.md)
adds a reproducible `scripts/wine-mod-smoke.py` experiment. Its real Windows/Wine
Palworld v1.0.5.102999 run loaded Pal Work Priority 0.5.0 with authority readiness,
authenticated REST info/players/save, graceful save/shutdown and a second container
start retaining the same empty-world identity. It publishes no ports and never
mounts existing game data. This does not add Wine support to the panel or establish
client/gameplay compatibility. Evidence is in [the result record](mod-smoke-results.json).

The REST shutdown configuration fix was also tested against a separate native
container using a copy of the disposable dev world: authenticated info/save and
the image's save/shutdown handlers succeeded. Regression coverage ensures REST
is enabled without publishing either management port. Both runtime wrappers
returned 143 after Docker's SIGTERM while logging successful REST save/shutdown;
that wrapper exit code is recorded rather than represented as a zero exit.

The supplied Base Radius Improved 1.2.2 archive was subsequently validated and
loaded alongside PWP. The optional `--base-radius-workshop` lab argument pins all
eight Lua hashes; regression tests reject altered/missing scripts, unreviewed
versions, extra executable files and symlinks, and prevent changing mods while the
lab container is active. Real combined tests cover startup, configuration creation,
save/restart, file-preserving disable/re-enable and world/configuration persistence.
There were no player-built bases or connected clients: Base Radius's authority
callback and actual expanded-base gameplay remain unverified. The panel's asset
library continues to reject executable code packages and RAR uploads.

The WSL execution sandbox prevents Starlette TestClient's thread event loop from
starting even for an empty FastAPI app; tests were run with approved loopback/thread
access outside that sandbox. This is an execution-environment constraint, not a reason
to bypass authentication. A Starlette deprecation warning about its current httpx
TestClient transport remains; the locked transport currently passes the tests.

## Disposable Docker and real Palworld

```bash
.venv/bin/python scripts/local-dev.py  # only once; refuses to overwrite .dev
# Run init outside a user namespace if it reports the socket group as nobody/nogroup.
docker compose --env-file .dev/.env -f compose.yaml up -d --build --wait
.venv/bin/python scripts/docker-smoke.py --install
.venv/bin/python scripts/runtime-smoke.py
.venv/bin/python scripts/isolation-smoke.py
.venv/bin/python scripts/docker-smoke.py --update
```

The exact disposable project prefix and all data roots live in `.dev/.env`.
The panel listens only on localhost:18080; the disposable game UDP port is 18211.
The controller has no published port. Both panel services use UID 1000, dropped
capabilities, read-only root filesystems and no-new-privileges. Only the controller
has the socket group/socket mount. Game data is a new bind directory under `.dev`.

Observed results:

- Compose build and web/controller health checks passed.
- DepotDownloader anonymously installed Steam app 2394010 into disposable data,
  downloading about 4.54 GB. The setup job completed inside its configured deadline.
- Native game v1.0.5.102999 started and returned authenticated RCON Info. An observed
  zero response ID required a protocol compatibility fix and a regression test.
- Start, stop and restart passed. Player listing returned an empty player list;
  Save succeeded. No real clients joined.
- A real Saved backup verified 56 files (about 108 KiB at that point). Dry-run and
  confirmed restore passed, previous Saved was retained, and the restored server
  initialized successfully. This is a newly generated world, not mature-world recovery.
- Local game memory remained inside a 4 GiB cap with no OOM in these short tests.
  This WSL machine has about 8 GB total RAM, below the image's published minimum;
  it is not a production load, stability, concurrency or capacity test.
- Upload/enable/disable/update/revert/remove passed through the real HTTP/controller
  stack with a synthetic PAK-shaped fixture while the game was stopped. The fixture
  was removed before starting the game. This proves management transactions only;
  it does **not** prove a third-party mod loads or is compatible with native Linux.
- One newly created unrelated sentinel container was rejected for start, stop,
  restart and remove; its Docker state was unchanged. Only its exact test ID was
  removed afterward. No existing unrelated workloads were enumerated or acted on.
- Controlled runtime update completed, including a pre-update Saved backup.
- Controller/web recreation retained registry ownership and game files. An interrupted
  install is never automatically restarted; unit tests cover failure/cancellation/recovery.

Browser smoke uses Chromium at desktop and 390px mobile widths. Login, server
navigation, Mods page, installation dialog and mobile no-overflow checks passed without
JavaScript exceptions. Screenshots are captured from the actual local application;
any sample mods are explicitly marked demo fixtures and never booted as real mods.

For optional browser automation:

```bash
uv pip install --python .venv/bin/python playwright==1.64.1
PLAYWRIGHT_BROWSERS_PATH="$PWD/.validation/browsers" .venv/bin/playwright install chromium
.venv/bin/python scripts/browser-smoke.py
```

## Static and supply-chain checks

Ruff, formatting, JavaScript syntax and Bandit checks pass. Bandit suppressions are
limited to the fixed subprocess worker, write-only password redaction and a container tmpfs literal; there is no
shell command built from request input. The hash-locked Python application requirements
have no known vulnerabilities in the completed pip-audit run. This does not cover
OS packages or proprietary game binaries.

Build then run `bash scripts/scan-images.sh` for digest-pinned Trivy scans using
exported image archives, no Docker socket in the scanner, and disk-backed temporary
files. Full local reports are `.validation/*-trivy.json`; the checked-in summary is
[docs/security-scan-summary.json](docs/security-scan-summary.json).

Final recorded panel-image scan: **0 critical, 46 high, 72 medium, 62 low, 6 unknown**
package findings, all in its upstream Debian base; the high findings have no fixed
version reported by that scan. Removing pip and its ensurepip bundle eliminated the
fixable Python packaging-tool findings; application Python packages reported none.

Pinned upstream Palworld image: **11 critical, 215 high, 442 medium, 318 low, 14 unknown**
package findings. Some have available fixes in upstream OS/Python/Go components;
they remain unresolved in the selected third-party image. Counts can repeat one CVE
across packages and do not establish remote exploitability. This runtime must receive
an upstream security update or a separately audited maintained derivative before
production acceptance. No findings are hidden with ignore-unfixed or arbitrary CVE ignores.

## Remaining production acceptance requirements

- Resolve or explicitly accept scanner findings after reviewing applicability, especially
  the Palworld image's critical/fixable findings. Re-scan replacement image digests.
- Test a licensed, author-supported, real native Linux mod with matching clients and
  game version. Official server Workshop/UE4SS automation currently targets Windows;
  native Linux asset compatibility is unverified and intentionally labeled that way.
- Verify real game-port binding and independent remote client connectivity; these
  health fields currently report unknown. Implement probes appropriate to the runtime.
- Validate HTTPS, proxy peer trust, Tailscale restrictions and private game access in
  a disposable network matching production. No Tailscale/firewall changes were made here.
- Test mature-world restores, off-host backup recovery, crash/power-loss durability,
  installation cancellation under real stalled networking, and long-running capacity.
- Investigate the previous host kernel/filesystem lockups independently; successful
  short WSL tests or rebooting cannot establish `homeserver` stability.
- Extend typed advanced Palworld configuration, reviewed policies for other games,
  update-discovery/version dependency constraints, and optional multi-user roles if needed.

Accordingly, this release is **not declared production-ready**. Unit and disposable
integration successes are reported separately from unresolved compatibility, upstream
vulnerabilities and production infrastructure checks.
