import hashlib
import socket

import pytest
from app import config, downloads


@pytest.mark.parametrize(
    "url",
    [
        "http://mods.example/file.zip",
        "file:///etc/passwd",
        "https://user:pass@mods.example/x",
        "https://mods.example:8443/x",
        "https://evil.example/x",
    ],
)
def test_download_url_policy(isolated, monkeypatch, url):
    monkeypatch.setattr(config, "DOWNLOAD_HOSTS", frozenset({"mods.example"}))
    with pytest.raises(ValueError):
        downloads.resolve(url)


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "::ffff:127.0.0.1", "100.100.100.100", "fe80::1"],
)
def test_private_dns_targets_rejected(isolated, monkeypatch, ip):
    monkeypatch.setattr(config, "DOWNLOAD_HOSTS", frozenset({"mods.example"}))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))])
    with pytest.raises(ValueError, match="public"):
        downloads.resolve("https://mods.example/x")


def test_redirect_revalidated_and_hash_checked(isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_HOSTS", frozenset({"mods.example"}))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])

    class Response:
        status = 302

        def getheader(self, name, default=None):
            return "https://127.0.0.1/private" if name == "Location" else default

    class Connection:
        def __init__(self, host, address, timeout):
            assert host == "mods.example" and address == "8.8.8.8"

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(downloads, "PinnedHTTPS", Connection)
    with pytest.raises(ValueError, match="host"):
        downloads.download("https://mods.example/x", tmp_path / "download", "a" * 64)


def test_download_limits_integrity_and_pinned_connection(isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_HOSTS", frozenset({"mods.example"}))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    payload = b"bounded download"

    class Response:
        status = 200
        offset = 0

        def getheader(self, name, default=None):
            return str(len(payload)) if name == "Content-Length" else default

        def read(self, size):
            result = payload[self.offset : self.offset + size]
            self.offset += len(result)
            return result

    class Connection:
        def __init__(self, host, address, timeout):
            assert address == "8.8.8.8"

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(downloads, "PinnedHTTPS", Connection)
    target = tmp_path / "good"
    downloads.download("https://mods.example/x", target, hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload
    with pytest.raises(ValueError, match="SHA-256"):
        downloads.download("https://mods.example/x", tmp_path / "bad", "a" * 64)
    monkeypatch.setattr(config, "MAX_UPLOAD", 5)
    with pytest.raises(ValueError, match="size"):
        downloads.download("https://mods.example/x", tmp_path / "big", "a" * 64)
