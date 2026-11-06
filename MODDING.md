# Palworld asset mod library

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
