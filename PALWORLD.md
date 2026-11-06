# Palworld operations

The approved runtimes are the native Linux amd64 build and a separately selected
Windows/Wine build of
[thijsvanloef/palworld-server-docker](https://github.com/thijsvanloef/palworld-server-docker).
Both checked digests are recorded in `.env.example`. The Windows/Wine runtime is
used only for an explicitly created or converted instance with reviewed UE4SS code
mods; conversion is covered in [MODDING.md](MODDING.md). GameHub fixes container
mounts, capabilities, resource limits, network, image and environment policy; the
UI cannot supply arbitrary Docker options. Other games are disabled pending reviewed
policies.

1. Create a server registration with a unique name, unused non-privileged UDP port,
   and an admin/RCON password of at least 16 characters. No download starts yet.
2. Choose **Install runtime**. The controller checks free disk, pulls the pinned
   image and starts a non-root setup-only container in the new instance directory.
3. Inspect progress in Console and the operation panel. Installation has a deadline
   (30 minutes production, 15 in the disposable WSL configuration). Cancel explicitly
   if needed. Failure preserves data and requires an intentional retry.
4. A zero-exit setup run and expected runtime files establish installation, not
   game readiness. Start the server, then inspect the distinct health checks.
5. Stop before editing settings or mods. A regular restart reuses game data and
   does not enable update-on-boot. Game **Update runtime** stops, verifies a Saved
   backup, runs setup/update, then resumes only if it was previously running.

DepotDownloader is the default via the image's `USE_DEPOT_DOWNLOADER` support;
`INSTALL_BACKEND=steamcmd` is an operator-selected alternative. See the
[image environment example](https://github.com/thijsvanloef/palworld-server-docker/blob/main/.env.example)
and [DepotDownloader project](https://github.com/SteamRE/DepotDownloader).
The outer controller imposes a deadline even if the runtime backend retries internally.
Cancelling an image-pull client cannot guarantee Docker immediately discards layers
already being downloaded; it never triggers daemon cleanup or an unrelated-container action.
No inference is made that SteamCMD caused the previous host kernel fault.

Settings expose name, description, player limit, join password and administrator
password. Passwords are write-only: blank fields keep existing passwords; the
explicit remove-password checkbox clears the join password. The maintained image
writes the game INI on boot. Raw filesystem/environment editors are intentionally
not exposed. Advanced settings beyond the typed form need a reviewed schema extension.

Console uses bounded authenticated polling. Allowed RCON commands are Info,
ShowPlayers, Save, Broadcast, KickPlayer and BanPlayer; enter supported game arguments
in the command field. Player listing is best-effort and may be unavailable while
initializing or when a game version changes its RCON behavior.

The runtime's authenticated REST API is also enabled on container port 8212 because
the pinned image uses it for graceful save/shutdown. It is never published to the
host. Existing containers need controlled recreation to receive environment changes;
restarting only the controller does not apply them. See the
[mod investigation](docs/palworld-mod-investigation.md) for the defect found during
Wine testing and the separately selectable Windows/Wine runtime.

Health reports independently:

- Container running: Docker state.
- Game process running: owned container process listing.
- Game initialized: expected version from the authenticated private REST API, with
  an RCON fallback for older containers.
- Game port bound: unknown until a dedicated port probe is implemented.
- External connectivity: unknown; an independent client/network check is required.

Never interpret running/initialized as successful external connectivity. The WSL
configuration caps game memory at 4 GB to protect this development host; it is below
the runtime's published minimum and is not a capacity test for production.
