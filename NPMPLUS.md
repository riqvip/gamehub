# NPMplus for GameHub

This optional **separate stack** initially exposes only the NPMplus administrator
interface on the operator-specified Tailscale IPv4 address, TCP 81. HTTP and HTTPS
initially listen only on host loopback, even if router forwards already exist.
It uses host networking as explicitly requested by the operator, with no Docker
socket or game-data mounts. This shares the host network namespace; it has less
network isolation than the previously tested bridge setup.
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
NPM_PROXY_IP=127.0.0.1
TZ=America/Los_Angeles
```

No shared Docker network is required. Then run:

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
container through `127.0.0.1:8000` on the host. Use the HTTP upstream
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

After TLS, login, origin trust and access policy are validated, set `NPM_PROXY_IP`
to the host's reserved LAN IPv4 address and recreate only this proxy service.
Host networking does not use Compose `ports` mappings. Public router forwarding
alone will not expose a listener bound only to loopback. Palworld UDP 8211 remains
separate from this HTTP proxy. Account sharing still grants full GameHub administrator
access; individual roles are not implemented by the current GameHub release.

## Validation and sources

The pinned image was first checked in a disposable local bridge container, then
the requested host-network configuration was checked using alternate loopback ports.
The admin HTTPS endpoint and connection to the disposable web health endpoint were
checked without controller or Docker access. This is an integration smoke test, not a full
security audit of NPMplus or its third-party dependencies.

The configuration adapts the [upstream Compose policy](https://github.com/ZoeyVid/NPMplus/blob/develop/compose.yaml)
and [setup documentation](https://github.com/ZoeyVid/NPMplus#quick-setup). The NPMplus
upstream license is AGPL-3.0-or-later; no NPMplus source is bundled in this repository.
