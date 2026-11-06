# Security policy and threat model

## Trust boundaries

GameHub is intended for a trusted administrator on a private network. Game players,
uploaded archives, URLs, forwarded HTTP headers and game-written files are untrusted.
Host administrators, Docker Engine, the selected runtime image, and private controller
configuration are trusted. There is one administrator; registration and anonymous
management are unavailable. Multi-user roles are not implemented.

The web service has no Docker socket or game data. Its controller credential grants
only explicit Palworld operations. The controller validates instance membership,
persisted Docker container ID, random ownership labels, approved image, network,
mounts and privileged settings before operating. Names alone never authorize actions.
It will not list unrelated containers, import volumes, accept arbitrary mounts, run
host commands, execute mod scripts, or accept Dockerfiles.

**Controller compromise remains host compromise.** Socket access is root-equivalent,
even when mounted read-only or accessed by a non-root process. Docker API restrictions
reduce the capabilities exposed to the web, but do not sandbox a compromised
controller. A dedicated host/VM or dedicated rootless daemon is a stronger boundary.
A compromised web process can disrupt its managed servers using legitimate API calls.
Game instances share a private game network; this does not isolate malicious game
processes from each other at the network layer.

## Authentication and browser security

Generate an Argon2id password hash; no plaintext/default password is supported.
Opaque random sessions are stored only as SHA-256 digests in SQLite, expire after
one hour, and can be revoked by logout. Cookies are HttpOnly, SameSite=Strict and
Secure by default. Mutations require a session-bound CSRF header; foreign Origin
headers are rejected. There is no credentialed CORS allowance. Logins are limited
to 5 attempts per source and 50 total per 15-minute window, persisted across restarts.
The global limit intentionally favors blocking brute force over availability.
Use a single web worker so operational limits are easy to reason about.

Forwarding headers are ignored unless the TCP peer belongs to `TRUSTED_PROXIES`.
X-Forwarded-For is evaluated from the trusted end of the chain; CF-Connecting-IP
has no authority. Uvicorn proxy handling is explicitly disabled so it cannot
rewrite the peer before the application checks it. Configure a proxy to overwrite
incoming forwarded headers. An explicit IP allowlist has no implicit localhost bypass.

CSP forbids inline scripts, framing, objects and external content; dynamic strings
use textContent. Tokens never appear in URLs or localStorage. WebSockets and public
status pages were removed; logs poll through normal authenticated API requests.
Passwords are write-only API fields; known passwords are redacted from game logs.
Game software can still emit other sensitive information: treat log access as admin-only.

## Files and downloads

Archive paths, CRCs, entry types, duplicate/case-colliding names, byte counts,
compression ratio and file counts are checked before deployment. Links, devices,
FIFOs, scripts, DLLs and loader binaries are rejected. Upload/JSON limits apply before
body parsing; disk limits, per-instance locks and stopped-server requirements protect
file operations. A signed mod manifest prevents trusting game-modified metadata.
The implementation assumes no hostile host administrator concurrently replaces
ancestors; it is not a kernel-level defense against a malicious host with filesystem access.

URL installation is disabled by default. Operators must permit exact HTTPS hosts,
including every redirect host. Every resolution rejects non-public addresses; the
TLS connection is pinned to a validated IP while retaining certificate/hostname
verification. Environment proxy settings are not used. Downloads require SHA-256,
have a total deadline, bounded redirects and size limits. DNS resolution itself
uses the OS resolver; configure bounded resolver timeouts on the host if required.

## Supply chain and reporting

Pinned image digests and hash-locked Python dependencies improve repeatability,
not image trust or game-binary provenance. Steam/depot downloads remain mutable
upstream content. Review image releases, scans and runtime behavior before changing
pins. See TESTING.md for outstanding scanner findings; scans are not a security proof.

Report suspected vulnerabilities privately to the fork maintainer through available
GitHub private vulnerability reporting, if enabled. Do not post credentials, worlds,
controller tokens, raw environment dumps, or exploitable details in public issues.
Back up configuration and revoke sessions after suspected compromise; rotate controller
credentials on both services together. Never attempt automatic host-level recovery.
