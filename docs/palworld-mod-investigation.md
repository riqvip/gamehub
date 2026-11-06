# Requested Palworld mods: investigation and local evidence

Investigated 2026-11-05 (America/Los_Angeles; execution logs cross into Nov 6 UTC).
Disable Drones is excluded as requested. This investigation does not change the
production server, migrate its world, or enable Windows runtime support in GameHub.

**Current result:** the supplied Base Radius Improved 1.2.2 archive was validated
and tested with Pal Work Priority 0.5.0 under Wine on Palworld v1.0.5.102999. Both
load together; save/restart and file-preserving disable/re-enable of Base Radius
passed on disposable data. Actual expanded-base and client gameplay remain untested.

## Exact selection and compatibility

| Package | Workshop ID | Evidence and decision |
| --- | --- | --- |
| [Base Radius Improved](https://steamcommunity.com/sharedfiles/filedetails/?id=3765017449) | 3765017449 | Supplied 1.2.2 package loads alongside PWP in Wine, creates its configuration and reads the vanilla radius. Restart/disable/re-enable passed. No real base/client gameplay or Base Radius authority callback has been established. |
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
or expanded-radius gameplay acceptance test. Combined startup does not establish
combined gameplay compatibility, nor compatibility of the two Sensible mods.

### Supplied Base Radius Improved archive

The subsequent `3765017449.rar` attachment is 296,495 bytes, SHA-256
`dc6c2789f7e249b9d39e32db9198dd40219d8b47f1e29f0b7e348f1c005c7b1a`.
Offline inspection found 11 regular files totaling 384,030 bytes, plus two
directories. All expected paths/sizes and extraction success were checked before
staging. The package includes Info.json naming `BaseRadiusImproved` version 1.2.2
and eight Lua scripts. Only those scripts were staged into the disposable server;
the attachment and third-party source are not committed or redistributed.

The real combined test observed:

- Both mods load together on v1.0.5.102999 with no initialization failure.
- Base Radius logs `v1.2.2 active` and `pristine snapshot captured (vanilla radius 3500)`.
  Its generated configuration contains 35 levels, with default radius from 35 m
  at level 1 to 94.5 m at level 35. Those are configuration values, not observed
  player/base behavior.
- Container recreation retains the world identity and Base Radius configuration.
- Removing Base Radius's enable marker and its mods.txt entry stops it loading;
  Pal Work Priority still reaches authority readiness. All original scripts and
  the configuration remain. Restoring both controls loads Base Radius again.
- Each run checks authenticated info/players/save and rejects unauthenticated save;
  the runtime logs its successful save/shutdown. No OOM occurred.

The optional combined harness was checked against a separate copy of the already
validated disposable Windows installation. An additional fresh download was
intentionally cancelled after slow Steam progress; it is not reported as a passed
fresh-install test. The original Windows/PWP fresh install had passed earlier.

**Base Radius authority is not yet verified.** Its source logs that role only once
base-camp objects exist. The test world has no player-built camp, so the missing
role line is recorded as unverified rather than treated as proof of success or
failure. Pal Work Priority's independent authority-readiness marker was observed.
Pal work coverage beyond the original radius, client dome rendering, upgrade UI,
client config synchronization, and two mods' real gameplay together still need a
matching client and a disposable base.

### Reproduce the Wine/PWP smoke test

From the repository, using the development dependencies and local Docker access:

```bash
.venv/bin/python scripts/wine-mod-smoke.py
```

To include the supplied package, extract it offline into a separate directory and
pass the folder that directly contains Info.json and Scripts:

```bash
.venv/bin/python scripts/wine-mod-smoke.py --base-radius-workshop /path/to/3765017449
```

The optional path accepts only the reviewed 1.2.2 package and the exact SHA-256 of
each of its eight scripts. Altered scripts, unexpected files, symlinks, missing
files and other versions fail before Docker starts. The combined run also tests
disable/re-enable without deleting source or changing the configuration. This does
**not** add RAR, Lua or DLL support to the panel's asset upload endpoint.

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

### Download retry: confirmed account restriction

Retried on 2026-11-05 in fresh restricted local containers:

- Official SteamCMD anonymous Workshop download failed again for item 3765017449.
  Its process still returned zero, so the download log and missing package files
  were checked rather than treating the exit code as success.
- Steam's official public `ISteamRemoteStorage/GetPublishedFileDetails/v1/` API
  returned successful public metadata for this item, but an empty `file_url`.
  There is no public direct-download URL in that response.
- [DepotDownloader's documented Workshop mode](https://github.com/SteamRE/DepotDownloader#downloading-a-workshop-item-using-pubfile-id)
  (`-app 1623730 -pubfile 3765017449`) connected and logged in anonymously, then
  explicitly reported **`App 1623730 (Palworld) is not available from this account.`**
  No mod files were downloaded.

This confirms an anonymous-account access limitation in the tested official paths,
not merely a guessed network timeout. Further anonymous retries cannot establish
the missing account access. Continue with an authorized Steam account or the
complete Workshop folder from a subscribed client. No alternate account, credentials,
unofficial downloader, protected endpoint scraping or permission bypass was used.
All retry containers were removed; the live server was untouched.

The user subsequently supplied the complete archive above, resolving the missing
package input without sharing Steam credentials. The anonymous-download limitation
remains relevant to future automated updates.

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

1. Test Base Radius Improved's authority log, actual radius, Pal coverage and
   save/reload using a player-built base on fresh disposable data. The complete
   authorized 1.2.2 package has now been supplied; another copy is not needed.
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
