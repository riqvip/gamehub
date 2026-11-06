# Requested Palworld mods: investigation and local evidence

Investigated 2026-11-05 (America/Los_Angeles; execution logs cross into Nov 6 UTC).
Disable Drones is excluded as requested. This investigation does not change the
production server, migrate its world, or enable Windows runtime support in GameHub.

## Exact selection and compatibility

| Package | Workshop ID | Evidence and decision |
| --- | --- | --- |
| [Base Radius Improved](https://steamcommunity.com/sharedfiles/filedetails/?id=3765017449) | 3765017449 | Author documents Windows dedicated installation and an authority-role log check. Candidate for Wine; not locally validated because the anonymous official Workshop download failed. Need the complete subscribed Workshop folder, including all eight Lua files. |
| [Pal Work Priority](https://steamcommunity.com/sharedfiles/filedetails/?id=3786408856) | 3786408856 | Current release 0.5.0 supports Windows dedicated servers. Server and modded clients must match exactly. Locally loaded under Wine and reached authority readiness on Palworld v1.0.5.102999; no client/gameplay test performed. |
| [Sensible Monitoring — Better Site Management](https://steamcommunity.com/sharedfiles/filedetails/?id=3806457819) | 3806457819 | Release 0.1.2 explicitly disables remote-client controls. Tested by its author in Windows single-player; dedicated/co-op unverified. Installing it on a server does not add its missing multiplayer controls. Exclude from the initial server test set. |
| [Sensible Base Shape — Square Bases](https://steamcommunity.com/sharedfiles/filedetails/?id=3806036478) | 3806036478 | Release 0.1.1 validates the supported Windows executable; only single-player tested. Dedicated servers and combination with other base-range mods remain unverified. Includes a native helper, so Lua portability alone is insufficient. Exclude from the initial server test set. |
| [UE4SS Experimental (Palworld)](https://steamcommunity.com/sharedfiles/filedetails/?id=3625223587) | 3625223587 | Loader dependency, not an additional gameplay mod. Use a single compatible loader installation; do not stack manual and Workshop loader copies. |

The author's [Pal Work Priority guide](https://github.com/Matraweber/PalWorkPriority#readme)
provides separate server instructions: the server needs its Scripts folder and
enabled.txt, but not the client UI PAK. The server's acceptance marker is
`PWP_READY version=0.5.0 ... role=authority settings=available`.
Players need their own compatible client installation. Server installation alone
does not install client UI files on their PCs.

Monitoring's [Nexus description](https://www.nexusmods.com/palworld/mods/5753)
and Square Bases' [Nexus description](https://www.nexusmods.com/palworld/mods/5741)
confirm these limitations. A modified multiplayer port would need author permission
where required by its license, native-code support for the dedicated executable,
server-authoritative operations and client synchronization. That is mod development,
not a GameHub setting. Nothing has been patched to bypass executable validation.

## Runtime choice

Pocketpair's [official server mod pipeline](https://docs.palworldgame.com/settings-and-operation/mod/)
supports the Windows dedicated edition. The maintained Docker runtime documents
[Windows/Wine mod operation](https://palworld-server-docker.loef.dev/guides/workshop-mods-and-ue4ss).
This still runs on Debian in Docker: it does not require replacing Debian with
Windows, installing Wine on the host, host GUI forwarding, or privileged containers.

The existing native Linux runtime explicitly receives `MOD_ENABLED=false` and starts
with `-NoMods`. The current browser asset library does not implement UE4SS/Lua loading.
Changing only that flag does not install a loader or validate any mod.

Native Linux UE4SS is **not impossible**. The experimental
[NullPrism port](https://github.com/NullPrism/RE-UE4SS-Linux) has a working loader,
including published BaseRadiusImproved authority-hook evidence, on an older target.
Its [compatibility matrix](https://github.com/NullPrism/RE-UE4SS-Linux/blob/main/docs/linux/COMPATIBILITY.md)
validates Palworld 1.0.2.100993/Fedora 43, not this server's 1.0.5.102999.
The maintainer does not recommend production yet. It cannot load a Windows native
helper DLL as a native Linux library. Wine is the first candidate tested here
because the requested mods document the Windows UE4SS path.

## Local execution evidence

The first disposable experiment established:

- Windows server installation through DepotDownloader completed with exit 0.
- Game v1.0.5.102999 booted with UE4SS and unmodified Pal Work Priority Lua code.
- The Lua files matched the public v0.5.0 tag byte-for-byte.
- `priority.log` reported version 0.5.0 loaded and `PWP_READY` with authority role
  and available settings. This is stronger than merely observing a running container.
- Authenticated private REST `/info`, `/players` and `/save` returned successfully;
  players were empty. Save and shutdown endpoints were logged during graceful stop.
- A separate negative authorization check confirmed that `/save` rejects a request
  without credentials. The new smoke script includes this check.
- The reproducible second experiment passed two container starts with fresh PWP
  readiness logs and an unchanged world identity after save/recreation. Both stops
  logged successful REST save/shutdown, no OOM, and wrapper exit 143 following
  Docker's SIGTERM. See [the sanitized result](../mod-smoke-results.json).
- A separate copy of the disposable native dev world also passed authenticated
  REST info/save and the image's own save/shutdown path with the controller fix.
- Test container UID/GID 1000, all capabilities dropped, no-new-privileges, 3 GiB
  memory cap, two CPUs, 512 PIDs, no restart policy and **no published ports**.
  Only fresh disposable game data was mounted, with no Docker socket or host secrets.
- The official anonymous SteamCMD request for Workshop item 3765017449 failed.
  SteamCMD nevertheless returned exit 0: that exit code is not proof of a mod download.
  No downloader service, account bypass, scraping or credential reuse was attempted.

The WSL host has about 8 GiB RAM and other local workloads. These empty-world tests
are not a capacity, stability, real-player, client synchronization, Pal work-priority,
or expanded-radius gameplay acceptance test. They do not establish compatibility of
both mods together, nor of the two Sensible mods.

### Reproduce the Wine/PWP smoke test

From the repository, using the development dependencies and local Docker access:

```bash
.venv/bin/python scripts/wine-mod-smoke.py
```

This creates a **new** `.validation/wine-mod-test-*` directory on every run. It
downloads the Windows server, verifies the pinned loader and source ZIP hashes,
boots the mod, checks authenticated readiness/save, recreates the disposable
container, and checks the world identity and mod readiness again. Each phase has
a deadline; failure requires an intentional new run. Ctrl+C stops the active owned
test container through the cleanup handler. Abruptly killing the Python process
or losing Docker connectivity may require manual cleanup of the exact ID recorded
in `active-container-id`; no global cleanup is attempted. Logs/data remain for review.

Pins used by the test:

- Wine image amd64 manifest: `sha256:911ec2b0fd9a3392e9ab687833344d3cda025998cce7dab11a943fa4cedb3e3f`
- UE4SS release `2281fa31`, ZIP SHA-256:
  `f7543d57f8fdf5eab3731ac52121e6e7ff142fb3bfa17156e931037d0e44875b`
- PalWorkPriority v0.5.0 tag: `dcc4811dc1117ef58a4f491d09c0513123ca0036`
- Source ZIP SHA-256:
  `03f7e7ceaa9156b2029dc81a0d120debb2c34918fd89ea853f6c4ad2f252483a`

The image is pinned, but Steam's live server depot may change. The result records
the actual game version. Re-check author support before testing a later game build.
Third-party files are fetched for the local test, not bundled into GameHub or
redistributed. Treat Lua/native mods as executable third-party code trusted inside
the game container. They are outside the ordinary asset-upload policy.

## Shutdown configuration defect found during testing

Both pinned runtime variants implement graceful save/shutdown through their internal
REST API. GameHub had set `REST_API_ENABLED=false`, causing the first Wine test to
log `REST_API save failed` and fall back to process termination. RCON availability
does not satisfy that runtime's shutdown implementation.

The controller now configures REST enabled on **8212 inside the game container**,
with the existing strong administrator password. Only UDP 8211 is published;
REST and RCON ports are never forwarded or mapped to the host. This lets the image's
own stop handler save and shut down correctly. Panel monitoring still uses RCON;
its deprecation warnings are a separate pending migration.

Changing controller code does not change an existing game container's environment.
An existing server needs a controlled container recreation after saving/backing up.
Do not assume a controller restart alone applies this fix. Nothing in this
investigation has recreated a production container or changed its data.

## Remaining work before use on a live world

1. Obtain the full Base Radius Improved subscribed Workshop folder from an authorized
   client (`steamapps/workshop/content/1623730/3765017449`); test its authority log,
   radius, Pal coverage and save/reload on fresh disposable data.
2. Run a real matching 0.5.0 client against the modded test server. Check priorities,
   limits, both mods together, reconnect and save/restart behavior. A startup marker
   cannot substitute for these checks.
3. Add a separately approved Windows runtime choice and typed code-mod workflow to
   GameHub. Keep fixed image policy, ownership verification, bounded operations,
   dependency/version checks and stopped-server transactions. The current asset ZIP
   upload must continue rejecting Lua/DLLs; do not relax it as a shortcut.
4. Verify a stopped-world backup before migration. Keep the native installation
   intact; create a separate Windows installation and copy the backup there.
   Preserve world ID, player data, server identity and platform-specific config,
   then test real player inventories/bases. A Linux-to-Windows migration of the
   existing live world has not been validated.
5. Resolve or assess the Wine image's scan findings and assess resource use under
   realistic player load. The pinned-image scan reported **6 critical and 203 high
   package findings**, including reported fixes for 2 critical and 23 high findings.
   These are scanner package counts, not demonstrated exploit paths. They remain
   unresolved; see [the scan summary](security-scan-summary.json). Pinning and a
   successful boot do not establish production readiness.

**Do not switch the existing game's image in place.** The upstream platform-switch
script removes Linux or Windows runtime files when it detects the other platform.
It is not a rollback-safe migration mechanism for the live world.
