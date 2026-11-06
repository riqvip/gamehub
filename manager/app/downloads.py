"""HTTPS-only downloads, exact host policy and DNS-pinned public connections."""

import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from . import config


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def resolve(url, allowed_hosts=None):
    part = urlsplit(url)
    host = (part.hostname or "").lower()
    if (
        part.scheme != "https"
        or part.port not in (None, 443)
        or part.username
        or part.password
        or part.fragment
    ):
        raise ValueError("Use an HTTPS download URL without credentials, custom ports or fragments")
    if host not in (config.DOWNLOAD_HOSTS if allowed_hosts is None else allowed_hosts) or not host:
        raise ValueError(
            "Download host is not enabled by the operator. Download manually and upload instead."
        )
    addresses = {x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Download target must resolve exclusively to public addresses")
    return part, sorted(addresses)[0]


def download(url, destination, expected_hash, *, allowed_hosts=None, deadline=None, cancel=None):
    deadline = min(time.monotonic() + 120, deadline or float("inf"))
    for _ in range(5):
        part, address = resolve(url, allowed_hosts)
        if time.monotonic() >= deadline or cancel and cancel.is_set():
            raise ValueError("Download deadline exceeded")
        conn = PinnedHTTPS(part.hostname, address, timeout=10)
        try:
            path = part.path or "/"
            if part.query:
                path += "?" + part.query
            conn.request("GET", path, headers={"User-Agent": "GameHub/2", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Invalid redirect")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"Download returned HTTP {response.status}")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ValueError("Encoded responses are unsupported")
            length = response.getheader("Content-Length")
            if length is not None and (int(length) > config.MAX_UPLOAD or int(length) < 0):
                raise ValueError("Download size limit exceeded")
            total, digest = 0, hashlib.sha256()
            with destination.open("xb") as output:
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > config.MAX_UPLOAD or time.monotonic() > deadline or cancel and cancel.is_set():
                        raise ValueError("Download size limit or deadline exceeded")
                    output.write(chunk)
                    digest.update(chunk)
            if length is not None and total != int(length):
                raise ValueError("Truncated download")
            if digest.hexdigest() != expected_hash.lower():
                raise ValueError("Download SHA-256 mismatch")
            return
        finally:
            conn.close()
    raise ValueError("Too many download redirects")
