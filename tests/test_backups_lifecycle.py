import os
import struct
import time
from unittest.mock import Mock

import pytest
from app import backups, config
from app import docker_service as ds
from app.models import CreateServerRequest
from app.palworld_config import dump_option_settings, parse_option_settings
from app.rcon import RconClient, RconError


def saved(server):
    path = ds.volume_path(server) / "Pal/Saved/SaveGames/world.sav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"disposable-world-fixture")
    return path


def test_backup_verified_restore_preview_confirmation_and_integrity(server):
    path = saved(server)
    b = backups.create_backup(server)
    assert b["verified"]
    path.write_bytes(b"changed")
    summary = backups.restore(server, b["filename"])
    assert summary["files"] == 1
    assert path.read_bytes() == b"changed"
    with pytest.raises(ValueError, match="confirm"):
        backups.restore(server, b["filename"], "wrong", False)
    backups.restore(server, b["filename"], "test-world", False)
    assert path.read_bytes() == b"disposable-world-fixture"
    assert (path.parents[2] / ".gamehub-restore-old/SaveGames/world.sav").read_bytes() == b"changed"
    archive, _ = backups.backup_paths(server, b["filename"])
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        backups.preview(server, b["filename"])


def test_live_backup_stops_and_restarts_only_on_success(server):
    saved(server)
    inst = ds.get_instance(server)
    inst["installed"] = True
    ds.save(inst)
    cont = ds.ensure_container(server)
    cont.start()
    result = backups.create_backup(server)
    assert result["consistency"] == "server-stopped"
    assert cont.status == "running"
    with pytest.raises(ValueError, match="Stop"):
        backups.restore(server, result["filename"], "test-world", False)


def test_no_empty_backups_and_no_traversal(server):
    with pytest.raises(ValueError, match="No Saved"):
        backups.create_backup(server)
    with pytest.raises(ValueError):
        backups.restore(server, "../other.zip")


def test_symlinks_and_hardlinks_rejected(server, tmp_path):
    path = saved(server)
    (path.parent / "link").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        backups.create_backup(server)
    (path.parent / "link").unlink()
    os.link(path, path.with_name("hardlink"))
    with pytest.raises(ValueError):
        backups.create_backup(server)


def test_retention_runs_after_success_and_is_instance_scoped(server):
    saved(server)
    inst = ds.get_instance(server)
    inst["backup_policy"]["retain"] = 1
    ds.save(inst)
    a = backups.create_backup(server)
    b = backups.create_backup(server)
    assert [r["filename"] for r in backups.list_backups(server)] == [b["filename"]]
    assert a["filename"] != b["filename"]


def test_restore_recovery_after_interruption(server):
    path = saved(server)
    root = path.parents[1]
    root.rename(root.parent / ".gamehub-restore-old")
    backups.recover(server)
    assert path.exists()


def test_container_policy_and_unknown_instance(isolated, server):
    with pytest.raises(KeyError):
        ds.stop("minecraft-existing")
    assert isolated.docker.calls == []
    cont = ds.ensure_container(server)
    kwargs = cont.kwargs
    assert kwargs["privileged"] is False and kwargs["user"] == "1000:1000"
    assert kwargs["cap_drop"] == ["ALL"] and kwargs["restart_policy"]["Name"] == "no"
    assert list(kwargs["ports"]) == ["8211/udp"]
    assert len(kwargs["volumes"]) == 1
    cont.attrs["Config"]["Labels"]["io.gamehub.owner"] = "wrong"
    with pytest.raises(ValueError, match="ownership"):
        ds.stop(server)
    assert cont.status == "created"


def test_runtime_can_save_on_shutdown_without_publishing_management_ports(server):
    cont = ds.ensure_container(server)
    env = cont.kwargs["environment"]
    assert env["REST_API_ENABLED"] == "true"
    assert env["REST_API_PORT"] == "8212"
    assert env["ADMIN_PASSWORD"] == ds.get_instance(server)["settings"]["admin_password"]
    assert set(cont.kwargs["ports"]) == {"8211/udp"}
    assert cont.kwargs["network"] != "host"


@pytest.mark.parametrize(
    "field,value",
    [
        ("Privileged", True),
        ("NetworkMode", "host"),
        ("CapAdd", ["SYS_ADMIN"]),
        ("PidMode", "host"),
        ("Devices", ["/dev/sda"]),
    ],
)
def test_mutated_container_policy_fails_closed(server, field, value):
    cont = ds.ensure_container(server)
    cont.attrs["HostConfig"][field] = value
    with pytest.raises(ValueError, match="policy"):
        ds.restart(server)


def test_unrelated_mount_rejected(server):
    cont = ds.ensure_container(server)
    cont.attrs["Mounts"][0]["Source"] = "/opt/data/mc-servers/modsquad"
    with pytest.raises(ValueError, match="mount"):
        ds.stop(server)


def test_start_stop_restart_preserves_data(server):
    path = saved(server)
    with pytest.raises(ValueError, match="Install"):
        ds.start(server)
    inst = ds.get_instance(server)
    inst["installed"] = True
    ds.save(inst)
    ds.start(server)
    assert ds.container_state(server) == "running"
    ds.restart(server)
    ds.stop(server)
    assert path.read_bytes() == b"disposable-world-fixture"


def test_no_adopting_existing_directories(isolated):
    (config.GAME_ROOT / "gh-existing").mkdir()
    with pytest.raises(ValueError, match="adopted"):
        ds.create_instance(CreateServerRequest(name="existing", settings={"admin_password": "x" * 16}))


def test_failed_install_job_is_explicit_and_stops(server, monkeypatch):
    import threading

    inst = ds.get_instance(server)
    inst["job"] = {"state": "running", "log": []}
    ds.save(inst)
    monkeypatch.setattr(ds, "pull_image", Mock(side_effect=TimeoutError("deadline")))
    ds.run_install(server, threading.Event(), False)
    assert ds.get_instance(server)["job"]["state"] == "error"
    assert "deadline" in ds.get_instance(server)["job"]["error"]


def test_cancel_job_and_job_lock(server):
    import threading

    inst = ds.get_instance(server)
    inst["job"] = {"state": "running", "log": []}
    ds.save(inst)
    event = threading.Event()
    ds._cancel[server] = event
    ds.cancel_install(server)
    assert event.is_set()
    with pytest.raises(ValueError, match="in progress"), ds.locked(server):
        pass


def test_settings_roundtrip_and_injection():
    values = {
        "ServerName": "Test, world",
        "ServerPlayerMaxNum": "16",
        "RCONEnabled": "True",
        "AdminPassword": "",
    }
    assert parse_option_settings(dump_option_settings(values)) == values
    for value in ['evil"Password="x', "line\nbreak", "back\\slash"]:
        with pytest.raises(ValueError):
            dump_option_settings({"ServerName": value})
    with pytest.raises(ValueError):
        parse_option_settings("OptionSettings=(A=1,A=2)")


def test_rcon_malformed_size_is_bounded():
    client = RconClient("localhost", 1, "password")
    client.deadline = time.monotonic() + 1
    client._sock = Mock()
    client._sock.recv.return_value = struct.pack("<iii", 2**30, 1, 2)
    with pytest.raises(RconError, match="packet size"):
        client._read_packet()


def test_successful_install_verified_without_claiming_game_readiness(server, monkeypatch):
    import threading

    inst = ds.get_instance(server)
    inst["job"] = {"state": "running", "log": []}
    ds.save(inst)
    monkeypatch.setattr(ds, "pull_image", lambda *args: None)
    original = ds.ensure_container

    def ensure(sid, setup=False):
        cont = original(sid, setup)
        if setup:
            (ds.volume_path(sid) / "PalServer.sh").write_text("#!/bin/sh\n")
            cont.start = lambda: setattr(cont, "status", "exited")
        return cont

    monkeypatch.setattr(ds, "ensure_container", ensure)
    event = threading.Event()
    monkeypatch.setattr(event, "wait", lambda *args: False)
    ds.run_install(server, event, False)
    assert ds.get_instance(server)["installed"] is True
    assert ds.get_instance(server)["job"]["state"] == "done"
    assert ds.container_state(server) == "created"


def test_cancelled_install_preserves_data(server, monkeypatch):
    import threading

    path = saved(server)
    inst = ds.get_instance(server)
    inst["job"] = {"state": "running", "log": []}
    ds.save(inst)
    monkeypatch.setattr(ds, "pull_image", lambda *args: None)
    event = threading.Event()
    event.set()
    ds.run_install(server, event, False)
    assert ds.get_instance(server)["job"]["state"] == "cancelled"
    assert path.exists()


def test_health_does_not_equate_running_with_ready(server, monkeypatch):
    from app import rcon_helpers

    cont = ds.ensure_container(server)
    cont.start()
    monkeypatch.setattr(rcon_helpers, "exec_rcon", Mock(side_effect=ValueError("not ready")))
    health = ds.stats(server)
    assert health["container_running"] is True
    assert health["game_initialized"] is False
    assert health["external_connectivity_verified"] is None


def test_backup_schedule_records_failure_without_restart_loop(server, monkeypatch):
    inst = ds.get_instance(server)
    inst["backup_policy"] = {"interval_hours": 1, "retain": 7}
    inst["created_at"] = time.time() - 7200
    ds.save(inst)
    create = Mock(side_effect=ValueError("disposable failure"))
    monkeypatch.setattr(backups, "create_backup", create)
    backups.schedule_tick()
    backups.schedule_tick()
    assert create.call_count == 1
    assert backups.read_json(backups.directory(server) / "schedule-status.json")["status"] == "error"


def test_palworld_zero_response_id_supported():
    client = RconClient("localhost", 1, "password")
    client._sock = Mock()
    client._read_packet = Mock(return_value=(0, 0, "Welcome to Pal Server[v1.0.5] Test"))
    assert "Pal Server" in client.exec("Info")
    client._read_packet = Mock(return_value=(7, 0, "unexpected"))
    with pytest.raises(RconError, match="response ID"):
        client.exec("Info")


def test_oom_or_forced_kill_is_not_a_consistent_backup(server):
    saved(server)
    cont = ds.ensure_container(server)
    cont.attrs["State"] = {"ExitCode": 137, "OOMKilled": True}
    with pytest.raises(ValueError, match="killed"):
        backups.create_backup(server)
    assert backups.list_backups(server) == []
