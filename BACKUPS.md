# Backup and recovery

GameHub backs up **only this managed instance's `Pal/Saved`**: worlds, player saves
and saved configuration. It does not traverse Minecraft paths or host volumes. Game
binaries, the controller's mod library, instance settings/ownership records and web
sessions are separate data requiring their own protected off-host backup.

## Create and retain

Choose **Backups → Create backup**. A running game is stopped first, and Docker's
stopped state is required before enumerating files. GameHub writes a ZIP with a
per-file SHA-256 inventory and archive checksum, checks CRCs, then publishes it and
applies retention. It starts the previously running game only after success. A
failure leaves the game stopped for investigation, rather than hiding a failure
behind automatic restart. Docker's graceful stop can still end with SIGKILL if the
runtime ignores its deadline: verify the runtime's save/shutdown behavior with real
worlds before trusting game consistency in production.

Scheduled backups use an interval in hours (0 disables) and a retain-latest count.
Only the controller runs the scheduler, once every 30 seconds; overlapping operations
are rejected. Failed scheduled attempts are persisted and retried only at the next
configured interval. No unlimited rapid retries occur. Schedule status appears in
the Backups tab. Retention is per instance and runs only after a verified new backup.

Archive/manifest files live in `BACKUP_DIR/<instance-id>/`. Backup destination is
configured by the operator's Compose bind, never a browser-supplied path. It can be
a dedicated mounted destination if independently verified by the operator. Defaults
limit uncompressed data to 16 GiB / 100,000 files. Links and special files are rejected;
insufficient disk produces an error. Files are stored without compression to avoid
CPU spikes and compression-ratio ambiguities; plan enough disk accordingly.

## Restore

1. Stop the target game; do not stop or modify unrelated workloads.
2. Select **Preview restore**. The server ID, archive checksum, inventory and byte
   limits are checked; the UI reports the file count and intended Saved destination.
3. Confirm the preview and type the exact instance name. Dry-run is the API default.
4. Extraction goes into temporary staging, rejects unsafe entries, and validates
   each SHA-256. Only then is Saved replaced. A partial extraction never replaces
   the original. The server remains stopped after restoration.
5. Previous Saved is retained as `Pal/.gamehub-restore-old`; the next successful
   restore replaces this recovery tree. Missing Saved after an interrupted rename
   is recovered from that tree before a subsequent start/restore.

Restore operates on Saved only; it does not roll back the runtime image or mod
library. Restore matching controller configuration/mod revisions separately if those
changed. Never restore by manually extracting arbitrary archives into `/opt/data`.
Do not delete the old recovery tree until independent verification is complete.

Export backup archives plus their adjacent `.json` manifests to independent storage.
Verify an off-host copy and periodically restore into a disposable instance. Filesystem
checksums establish integrity, not Palworld save semantics or successful client joins.
