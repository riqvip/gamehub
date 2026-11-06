# NPMplus for GameHub

This optional **separate stack** initially exposes only the NPMplus administrator
interface on the operator-specified Tailscale IPv4 address, TCP 81. It publishes
neither public port 80 nor public port 443, even if router forwards already exist.
It uses a Docker bridge and has no Docker socket, host networking or game-data mounts.
No SSH, Tailscale or firewall configuration is changed.

## First start

Check for existing listeners on 80/81/443, an existing Compose project named
`npmplus`, and existing `/opt/stacks/npmplus` or `/opt/data/npmplus` directories.
Never overwrite a prior proxy installation. The image requires x86-64-v2 or better
on amd64; check `/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 --help` if unsure.

On a clean target, create `/opt/stacks/npmplus` owned by the operator, then create
`/opt/data/npmplus` owned by root with mode 0700. The image's default PUID is root;
only the two capabilities in its upstream default policy are restored after dropping
all capabilities. It is not a privileged container. Its filesystem is writable as
required by the image's initialization; persistence is limited to its own `/data` bind.

Copy `deploy/npmplus.compose.yaml` to `/opt/stacks/npmplus/compose.yaml`. Create an
adjacent `.env` containing:

```dotenv
NPM_ADMIN_IP=YOUR_HOST_TAILSCALE_IPV4
TZ=America/Los_Angeles
```

The existing GameHub stack must have created `gamehub_frontend`; customize
`GAMEHUB_FRONTEND_NETWORK` if its project name differs. Then run:

```bash
cd /opt/stacks/npmplus
docker compose config --quiet
docker compose up -d --wait --wait-timeout 180
```

Open `https://YOUR_HOST_TAILSCALE_IPV4:81` from a Tailscale-connected device. The
initial certificate is self-signed: a browser certificate warning at this specific
private bootstrap URL is expected. Complete the first-run administrator setup and
enable MFA. No shared/default administrator password is supplied by this configuration.
Never forward router port 81 to this service.

## Before publishing GameHub

The chosen dashboard hostname is `gamehub.riqvip.dev`. NPMplus can reach the web
container as `gamehub-web-1:8000` on the frontend bridge. Use the HTTP upstream
scheme; the browser-facing proxy terminates HTTPS. Configure the original Host
header normally, add the domain to GameHub's `ALLOWED_HOSTS`, keep `COOKIE_SECURE=true`,
and configure explicit trusted proxy IPs before relying on client-IP throttling.
Do not trust every internet forwarding header or broadly trust unrelated networks.

Obtain a real certificate before exposing the hostname. Cloudflare DNS validation
can issue certificates without inbound port forwarding; enter a zone-scoped token
directly in NPMplus, never in chat or Git. With Cloudflare's proxy disabled, NPMplus
serves the certificate directly. If the Cloudflare HTTP proxy is intentionally used,
configure Full (strict), review its upload limits, and establish a separate policy
for trusted Cloudflare source addresses.

Adding public port mappings is a later explicit step, after TLS, login, origin trust
and access policy are validated. Public router forwarding alone will not expose a
listener that this initial Compose file does not publish. Palworld UDP 8211 remains
separate from this HTTP proxy. Account sharing still grants full GameHub administrator
access; individual roles are not implemented by the current GameHub release.

## Validation and sources

The pinned image was checked in a disposable local bridge container with only
loopback admin TCP 18081 published. Its built-in health check passed, the private
HTTPS page returned HTTP 200, and it reached the disposable web health endpoint
without controller or Docker access. This is an integration smoke test, not a full
security audit of NPMplus or its third-party dependencies.

The configuration adapts the [upstream Compose policy](https://github.com/ZoeyVid/NPMplus/blob/develop/compose.yaml)
and [setup documentation](https://github.com/ZoeyVid/NPMplus#quick-setup). The NPMplus
upstream license is AGPL-3.0-or-later; no NPMplus source is bundled in this repository.
