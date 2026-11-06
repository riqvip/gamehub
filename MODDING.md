# Palworld mods

For the requested Workshop mods, loader research and actual local Wine/PWP evidence,
see [the mod investigation](docs/palworld-mod-investigation.md). GameHub now has two
deliberately separate paths:

- **Native Linux asset library** — stages PAK/UTOC/UCAS files only. The native runtime
  still starts with `-NoMods`; an enabled library entry is not proof of game loading.
- **Windows/Wine reviewed code mods** — a separate runtime per instance with a pinned
  UE4SS loader and only the exact reviewed Lua packages. This executes third-party
  code inside the game container.

## Windows/Wine reviewed code mods

Open **Mods → Switch to Windows/Wine**. The server must be stopped and installed.
GameHub then:

1. creates a verified backup of the native world;
2. creates a separate `<instance>-runtime-<random>` data directory, leaving the
   native installation untouched, and copies `Pal/Saved` into it;
3. installs the pinned Windows server and verifies `PalServer.exe`;
4. installs the pinned UE4SS release and creates a signed loader marker;
5. removes the setup container and records the instance as a Windows/Wine server.

The conversion and download run as a normal cancellable job. It copies `Pal/Saved`
only, not the native asset library's staged PAK files. The original native files
remain in place; **Return to native runtime** removes the Windows container and
repoints the instance at the untouched native directory. The separate Windows
directory is retained for inspection rather than deleted.

Only these exact versions are accepted:

| Package | Version | Source |
| --- | --- | --- |
| Base Radius Improved | 1.2.2 | Upload a ZIP containing the complete `Scripts` folder |
| Pal Work Priority | 0.5.0 | **Download pinned release** (verified GitHub tag) or upload the same scripts |

The panel rejects altered scripts, other versions, missing files, RAR archives and
arbitrary Lua. Only the exact reviewed `Scripts` tree is installed; other archive
contents are ignored and never copied into the server. Uploaded code is installed
**disabled**;
enabling requires an acknowledgement. Enable/disable writes `mods.txt` and preserves
the mod files, so a later re-enable is file-preserving. Removal requires the mod to
be disabled first. For Pal Work Priority, disable it in-game and load once before
removal so its work permissions are restored.

The server's UE4SS folder is managed: startup refuses unmanaged top-level mod files,
changed `mods.txt`, unexpected `enabled.txt` markers and loader/script hash mismatches.
Player PCs are not managed by GameHub. Every player needs the matching client mod
version and UE4SS; installing only the server side does not add client UI files or
synchronize the client installation.

Actual expanded-base gameplay, Pal work coverage, client dome rendering and
multiplayer client synchronization remain unverified. See
[the investigation](docs/palworld-mod-investigation.md) and [TESTING.md](TESTING.md).

## Compatibility evidence

Pocketpair's [current server mod guide](https://docs.palworldgame.com/settings-and-operation/mod/)
states official server-side mod support is for Windows. The runtime image likewise
marks its Workshop loader settings Windows-only. GameHub therefore labels every
native Linux asset package **unverified**, installs it disabled, and requires an
acknowledgement before deployment. Static inspection is not proof of successful
loading, safe execution, server/client compatibility or save compatibility.

Native Linux UE4SS forks may exist, but GameHub does not install or execute them.
DLLs, Lua, ELF loaders, scripts, Wine/Proton and official Windows Workshop manifests
are unsupported. The old misleading one-click UE4SS catalog has been removed.
No real, licensed, known-compatible mod is claimed as validated unless TESTING.md
records its runtime test. Synthetic PAK fixtures test safety/workflow only.

## Upload and use

Stop the server. Open **Mods → Install a mod**, upload `.zip` or `.pak`, inspect the
library entry, then decide whether to enable it. ZIP supports `.pak`, paired
`.utoc`/`.ucas`, and associated UTF-8 `.ini`. A PAK footer or TOC header is a coarse
format check, not full Unreal parsing. UCAS is checked as a non-executable companion;
its payload is not semantically parsed. Configuration-only packages are rejected;
INI companions are retained beside assets, not installed into arbitrary game paths.

Nested archive wrapper paths are validated then flattened to filenames. Case-folded
duplicates are rejected. Assets deploy only to the managed `Pal/Content/Paks/~mods`
directory. An existing unmanaged directory is never adopted. Conflicting enabled
filenames are rejected without overwriting the active deployment. The administrator
must verify this layout is appropriate for each mod and game version.

The library supports name/author/version search, status filters, sorting, source,
installation time, dependency IDs, compatibility, installation history, enable,
disable, remove, update and revert. An update uploads a replacement to the selected
package; its previous revision is retained. Failed validation/conflicts preserve the
previous active tree. Disabling removes deployment but preserves the library copy.
Removed/historical revisions are retained in controller configuration for recovery;
there is no automatic revision garbage collector. Include this directory in capacity
planning and protected off-host backups.

Optional `gamehub-mod.json` inside a ZIP:

```json
{
  "name": "Example asset package",
  "description": "Author's dedicated-server instructions apply",
  "version": "1.2",
  "author": "Example author",
  "source": "Author release page",
  "dependencies": []
}
```

Dependencies are library package IDs, not inferred external mod identifiers. Missing
dependencies prevent installation; enabling requires enabled dependencies. Version
constraints and automatically discovering updates are not implemented: the UI says
**Not checked**, never **Up to date**. Update compatibility remains unverified.

Uploads: 128 MiB compressed, 512 MiB extracted, 2,048 entries, compression ratio
at most 300:1. Paths, CRCs, actual streamed bytes, duplicate names, symlinks and
special files are checked in temporary staging. The whole managed deployment tree
and signed manifest switch together, with recovery of interrupted directory swaps.
There is a brief stopped-server gap between the two renames; this is not an atomic
exchange syscall. World backups are independent of mod revisions.

## URL and Nexus workflows

URL installs require an operator-configured exact HTTPS host allowlist and an
expected SHA-256. Every redirect is revalidated, and the download socket connects
to a vetted public IP with normal TLS verification. Signed query parameters are not
persisted as mod source metadata. If a host is disabled, download manually and upload.

Nexus integration deliberately provides **Open Palworld on Nexus → download with
your account → upload the archive**. It performs no scraping or credential sharing.
The [official Nexus API client](https://github.com/Nexus-Mods/node-nexus-api/blob/master/docs/classes/_nexus_.nexus.md)
documents account-dependent download links: non-premium accounts need a website-issued
key/expiry. A future direct integration must implement personal authorization,
permissions and current API rate-limit headers, respecting the
[API acceptable-use policy](https://help.nexusmods.com/article/114-api-acceptable-use-policy).
The [current quota guidance](https://help.nexusmods.com/article/105-i-have-reached-a-daily-or-hourly-limit-api-requests-have-been-consumed-rate-limit-exceeded-what-does-this-mean)
should be checked at integration time; historical hard-coded quotas are inappropriate.
Mod licensing is determined by each author; an API key does not grant redistribution
rights. GameHub bundles no third-party mods or another user's credentials.
