"""Forwarded headers have authority only across explicitly trusted proxy hops."""

import ipaddress

from . import config


def networks(raw):
    return [ipaddress.ip_network(x.strip(), strict=False) for x in raw.split(",") if x.strip()]


def in_networks(ip, nets):
    addr = ipaddress.ip_address(ip)
    return any(addr in net for net in nets)


def client_ip(req):
    peer = req.client.host if req.client else ""
    try:
        trusted = networks(config.TRUSTED_PROXIES)
        ipaddress.ip_address(peer)
        if not in_networks(peer, trusted):
            return peer
        # Walk backwards; the first untrusted hop is the client. Never trust CF headers.
        chain = req.headers.get("x-forwarded-for", "").split(",")
        if len(chain) > 20:
            return "invalid"
        current = peer
        for hop in reversed(chain):
            if not in_networks(current, trusted):
                break
            current = str(ipaddress.ip_address(hop.strip()))
        return current
    except ValueError:
        return "invalid"


def is_allowed(ip):
    try:
        ipaddress.ip_address(ip)
        return not config.ADMIN_ALLOWED_IPS or in_networks(ip, networks(config.ADMIN_ALLOWED_IPS))
    except ValueError:
        return False
