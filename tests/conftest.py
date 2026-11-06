import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app import auth, config
from app import docker_service as ds
from app.models import CreateServerRequest
from docker.errors import NotFound


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for key, sub in (
        ("DATA_DIR", "web"),
        ("CONFIG_DIR", "config"),
        ("BACKUP_DIR", "backups"),
        ("GAME_ROOT", "games"),
    ):
        path = tmp_path / sub
        path.mkdir()
        monkeypatch.setattr(config, key, path)
    monkeypatch.setattr(config, "HOST_GAME_ROOT", str(config.GAME_ROOT))
    monkeypatch.setattr(config, "ADMIN_PASSWORD_HASH", auth.ph.hash("test-password-very-strong"))
    monkeypatch.setattr(config, "CONTROLLER_TOKEN", "t" * 43)
    monkeypatch.setattr(config, "PALWORLD_IMAGE", "thijsvanloef/palworld-server-docker@sha256:" + "a" * 64)
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(config, "ALLOWED_HOSTS", ["testserver", "localhost"])
    monkeypatch.setattr(config, "ADMIN_ALLOWED_IPS", "")
    monkeypatch.setattr(config, "TRUSTED_PROXIES", "")
    monkeypatch.setattr(config, "MIN_FREE_BYTES", 0)
    monkeypatch.setattr(config, "MAX_EXTRACTED", 1024**2)
    monkeypatch.setattr(ds, "_locks", {})
    monkeypatch.setattr(ds, "_cancel", {})
    fake = FakeDocker()
    monkeypatch.setattr(ds, "_docker", fake)
    return SimpleNamespace(root=tmp_path, docker=fake, monkeypatch=monkeypatch)


class FakeContainer:
    def __init__(self, image, **kwargs):
        self.id = "container-" + kwargs["name"]
        self.status = "created"
        self.kwargs = kwargs
        self.attrs = {
            "Config": {"Labels": kwargs["labels"], "Image": image},
            "HostConfig": {"NetworkMode": kwargs["network"], "Privileged": False},
            "Mounts": [
                {"Type": "bind", "Source": source, "Destination": values["bind"]}
                for source, values in kwargs["volumes"].items()
            ],
            "State": {"ExitCode": 0},
            "NetworkSettings": {"Networks": {kwargs["network"]: {"IPAddress": "172.25.0.2"}}},
        }
        self.reload = Mock()
        self.removed = False

    def start(self):
        self.status = "running"

    def stop(self, **kwargs):
        self.status = "exited"

    def remove(self, **kwargs):
        self.removed = True

    def logs(self, **kwargs):
        return b"Palworld logs\n"

    def stats(self, **kwargs):
        return {"memory_stats": {"usage": 1024**2}}

    def top(self):
        return {"Processes": [["PalServer-Linux-Shipping"]]}


class FakeDocker:
    def __init__(self):
        self.items = {}
        self.calls = []
        self.containers = SimpleNamespace(get=self.get, create=self.create)

    def get(self, key):
        self.calls.append(("get", key))
        if key not in self.items or self.items[key].removed:
            raise NotFound("missing")
        return self.items[key]

    def create(self, image, **kwargs):
        self.calls.append(("create", copy.deepcopy(kwargs)))
        c = FakeContainer(image, **kwargs)
        self.items[c.id] = c
        return c


@pytest.fixture
def server(isolated):
    body = CreateServerRequest(name="test-world", settings={"admin_password": "game-password-very-strong"})
    ds.create_instance(body)
    return "gh-test-world"


@pytest.fixture
def web(isolated):
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client


@pytest.fixture
def logged_in(web):
    response = web.post("/api/login", json={"username": "admin", "password": "test-password-very-strong"})
    assert response.status_code == 200
    web.headers["x-csrf-token"] = response.json()["csrf"]
    return web


@pytest.fixture
def controller(isolated):
    from app.controller import app
    from fastapi.testclient import TestClient

    with TestClient(app, headers={"Authorization": "Bearer " + config.CONTROLLER_TOKEN}) as client:
        yield client
