import time

import pytest
from app import auth, config, ip_gate
from app.models import Settings
from app.storage import checked
from starlette.requests import Request


def test_no_default_authentication(isolated, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD_HASH", "")
    with pytest.raises(RuntimeError):
        auth.validate()


def test_session_csrf_revocation_and_security_headers(logged_in):
    client = logged_in
    response = client.get("/api/session")
    assert response.status_code == 200
    assert "'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert client.post("/api/logout", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.post("/api/logout", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/session").status_code == 401


def test_session_cookie_http_only_and_no_bearer_token(web):
    r = web.post("/api/login", json={"username": "admin", "password": "test-password-very-strong"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "access_token" not in r.json()
    with auth.database() as db:
        token_hash = db.execute("SELECT id FROM sessions").fetchone()[0]
    assert token_hash != web.cookies.get("gamehub_session")


def test_expired_session(logged_in):
    with auth.database() as db:
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert logged_in.get("/api/session").status_code == 401


def test_login_throttle_and_no_default_password(web):
    for _ in range(5):
        assert web.post("/api/login", json={"username": "admin", "password": "changeme"}).status_code == 401
    assert (
        web.post(
            "/api/login", json={"username": "admin", "password": "test-password-very-strong"}
        ).status_code
        == 429
    )


def test_unauthenticated_and_removed_surface(web):
    for path in ("/api/servers", "/api/activity", "/api/servers/gh-test/mods"):
        assert web.get(path).status_code == 401
    assert web.get("/public/servers").status_code == 404
    assert web.get("/share/gh-test").status_code == 404
    assert web.get("/docs").status_code == 404
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), web.websocket_connect("/api/servers/gh-test/logs/ws?token=test"):
        pass


def test_build_and_arbitrary_proxy_paths_unavailable(logged_in):
    for path in ("servers/gh-test/build", "../healthz", "containers/json", "servers/gh-test/exec"):
        assert logged_in.post("/api/" + path, json={}).status_code in (404, 405)


def test_origin_login_and_cors(web):
    assert (
        web.post(
            "/api/login",
            headers={"Origin": "https://evil.example"},
            json={"username": "admin", "password": "x"},
        ).status_code
        == 403
    )
    assert (
        "access-control-allow-origin" not in web.get("/", headers={"Origin": "https://evil.example"}).headers
    )


def request(peer, forwarded="", cf=""):
    return Request(
        {
            "type": "http",
            "client": (peer, 1234),
            "headers": [(b"x-forwarded-for", forwarded.encode()), (b"cf-connecting-ip", cf.encode())],
        }
    )


def test_untrusted_proxy_headers_are_ignored(isolated):
    assert ip_gate.client_ip(request("198.51.100.3", "127.0.0.1", "127.0.0.1")) == "198.51.100.3"


def test_trust_chain_stops_at_first_untrusted_proxy(isolated, monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXIES", "10.0.0.0/24")
    assert ip_gate.client_ip(request("10.0.0.5", "127.0.0.1, 198.51.100.4, 10.0.0.6")) == "198.51.100.4"
    assert ip_gate.client_ip(request("10.0.0.5", "bad")) == "invalid"
    monkeypatch.setattr(config, "ADMIN_ALLOWED_IPS", "10.0.0.0/24")
    assert not ip_gate.is_allowed("127.0.0.1")


def test_ip_gate_covers_login_and_static(web, monkeypatch):
    monkeypatch.setattr(ip_gate, "client_ip", lambda request: "198.51.100.2")
    monkeypatch.setattr(config, "ADMIN_ALLOWED_IPS", "10.0.0.0/24")
    assert web.get("/").status_code == 403
    assert web.post("/api/login", json={"username": "admin", "password": "x"}).status_code == 403
    assert web.get("/healthz").status_code == 200


def test_request_size_rejected_before_json(web, monkeypatch):
    r = web.post("/api/login", content=b"a" * 65537, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_controller_requires_independent_token(controller):
    assert controller.get("/v1/servers", headers={"authorization": "Bearer bad"}).status_code == 401
    assert controller.get("/v1/servers").status_code == 200


@pytest.mark.parametrize(
    "extra", [{"image": "evil"}, {"dockerfile": "FROM evil"}, {"volumes": {}}, {"game": "minecraft"}]
)
def test_fixed_controller_policy(controller, extra):
    body = {"name": "test", "settings": {"admin_password": "a" * 16}, **extra}
    assert controller.post("/v1/servers", json=body).status_code == 422


def test_secrets_not_returned(controller, server):
    response = controller.get(f"/v1/servers/{server}")
    assert response.status_code == 200
    assert "owner" not in response.json()
    assert "game-password" not in response.text
    settings = controller.get(f"/v1/servers/{server}/settings").json()
    assert settings["admin_password"] == ""


@pytest.mark.parametrize(
    "key,value",
    [
        ("server_name", 'bad"Injected=True'),
        ("server_name", "bad\nline"),
        ("players", 999),
        ("admin_password", "short"),
    ],
)
def test_configuration_values_validated(isolated, key, value):
    with pytest.raises(ValueError):
        Settings.model_validate({"admin_password": "a" * 16, key: value})


def test_no_symlink_paths(isolated):
    link = isolated.root / "games" / "link"
    link.symlink_to(isolated.root / "config", target_is_directory=True)
    with pytest.raises(ValueError):
        checked(link, "file")


def test_chunked_body_limit_before_parsing(web):
    def chunks():
        for _ in range(10):
            yield b"x" * 10000

    response = web.post("/api/login", content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_upload_limits_and_malicious_archive_api(controller, server, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD", 10)
    assert (
        controller.post(
            f"/v1/servers/{server}/mods/upload", content=b"x" * 11, headers={"x-filename": "test.pak"}
        ).status_code
        == 413
    )
    assert (
        controller.post(
            f"/v1/servers/{server}/code-mods/upload",
            content=b"x" * 11,
            headers={"x-filename": "test.zip"},
        ).status_code
        == 413
    )


def test_secure_cookie_configuration(web, monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    response = web.post("/api/login", json={"username": "admin", "password": "test-password-very-strong"})
    assert "; secure" in response.headers["set-cookie"].lower()
