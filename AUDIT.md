# GameHub security audit

Baseline: upstream-derived commit `0d1ae75`; all tracked Python, JavaScript,
HTML, Compose, Dockerfile, dependency declarations and installer reviewed.
The screenshot and icon are non-executable assets. Audit began before changes.

| Finding | Severity / prerequisites | Baseline impact | Remediation |
| --- | --- | --- | --- |
| Docker socket in web process; arbitrary images/builds | Critical; web compromise or admin account | Host-equivalent Docker control; access to unrelated workloads | Private authenticated controller, fixed Palworld runtime, persisted container ID and ownership secret, policy checks; remove generic images/build endpoints |
| Known password and signing key; SHA-256 password verifier | Critical with unchanged defaults | Predictable admin access and forged tokens | Required Argon2id hash, opaque revocable sessions, startup validation |
| Unbounded ZIP extraction and file writes | High; authenticated upload | Traversal, symlinks, decompression denial of service, overwrite | Bounded staged extraction, file allowlist, stopped-server transactions, conflict checks |
| Arbitrary URL fetch and redirects | High; authenticated administrator | SSRF to local/internal services and unbounded downloads | Disabled unless operator permits exact HTTPS hosts; DNS and redirect checks, pinned public IP connection, size/deadline/hash validation |
| Forwarded headers trusted from anyone | High if IP gating used | Bypass admin IP allowlist | Explicit proxy networks; right-to-left trust-chain evaluation; ignore CF header |
| WebSocket checks only JWT signature | High with valid wrong-subject token | IP/subject policy bypass; token in URLs, unbounded queue/thread | Remove WebSockets; authenticated bounded polling with session checks on every request |
| Public player/status rendering uses innerHTML | High; malicious player name or stored value | Stored XSS, theft of localStorage bearer token | Remove anonymous status endpoints; textContent rendering, CSP, HttpOnly cookie |
| Broad credentialed CORS; no session revocation or login throttling | High / medium; network access | Brute force, broad browser attack surface | Same-origin API, CSRF token and Origin validation, persistent throttling and expiry/revocation |
| File/config paths follow symlinks; restore is manual host tar extraction | High; malicious game files or admin mistake | Write/read outside instance; unrelated data damage | Controller-owned roots, path checks, stopped-only managed operations, validated restore with preview and confirmation |
| Backup during world writes; no verification/retention/restore | High operational risk | Inconsistent saves; silent data loss | Controlled stop, checksum verification, bounded restore staging, retention and schedule |
| Name-only container lookup and broad exception suppression | High; colliding preexisting names or Docker failure | Modify unrelated container; false success, orphaned state | Registry ownership + exact Docker ID + labels + mount/network policy; fail closed |
| Installer changes firewall/system services and publishes panel | High operational risk; root installer | Public exposure and changes outside project | Retire installer; loopback Compose deployment with explicit operator setup |
| Mutable images, outdated pins, no tests/scans/resources | Medium to high; vulnerable dependency/image | Supply-chain exposure; host resource exhaustion | Refreshed locked Python dependencies, digest selection, scans/tests, bounded resources and retries |
| Loose settings parser/RCON response sizes | Medium; malformed input/compromised game | Config injection, memory growth, wrong target | Typed settings; bounded RCON packets; container-network address only |

The controller remains a sensitive host component: its Docker socket grants
root-equivalent authority if the controller itself is compromised. Its API is a
reduction in exposed capability, not a complete container-escape boundary.
A compromised web process can exercise allowed controller actions and disrupt
GameHub-owned servers. Host administrators and the selected runtime remain trusted.

Validation results, unresolved requirements and runtime compatibility evidence
are recorded in TESTING.md and MODDING.md as implementation progresses.

## Remediation validation

The rewritten API removes arbitrary builds/images, generic environment/filesystem
editors, anonymous sharing and WebSockets. Tests and a disposable real-game deployment
validate the replacement capabilities; see TESTING.md. No default-password or old JWT
path remains. Host installation behavior is retired. Supported policy is intentionally
Palworld-only; the original other-game support is not silently retained behind an
unrestricted Docker API.

Upstream image vulnerability findings remain open: the recorded Palworld image scan
has critical and fixable package findings. The panel's remaining high findings are in
its upstream Debian base with no fixed version reported by the scan. Exact critical
packages/versions and counts are in docs/security-scan-summary.json. These are release
acceptance risks, not treated as resolved by non-root execution or a private network.
A real native Linux third-party mod has not been validated; no compatibility claim is
made from synthetic archive tests.
