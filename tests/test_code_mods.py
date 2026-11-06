"""Reviewed Windows/Wine packages and the separate-runtime transaction."""

import hashlib
import json
import zipfile

import pytest
from app import code_mods
from app import docker_service as ds
from app.models import CreateServerRequest

SCRIPT = b"-- synthetic reviewed Lua fixture; never executed\n"
PACKAGE = "SyntheticReviewed"


def windows_server(settings=None, port=8211):
    body = CreateServerRequest(
        name="wine-world",
        game_port=port,
        runtime="windows-wine",
        acknowledge_code_mods=True,
        settings=settings or {"admin_password": "game-password-very-strong"},
    )
    ds.create_instance(body)
    return "gh-wine-world"


def synthetic_catalog():
    return {
        PACKAGE: {
            "name": "Synthetic reviewed mod",
            "version": "1.0.0",
            "author": "Test author",
            "source": "https://example.invalid/reviewed",
            "description": "Synthetic fixture",
            "scripts": {"main.lua": hashlib.sha256(SCRIPT).hexdigest()},
        }
    }


def write_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return path


def loader_archive(tmp_path):
    return write_zip(
        tmp_path / "loader.zip",
        {
            "dwmapi.dll": b"proxy fixture",
            "ue4ss/LICENSE": b"loader license fixture",
            "ue4ss/UE4SS-settings.ini": b"[Settings]\n",
            "ue4ss/Mods/shared/UEHelpers/UEHelpers.lua": b"-- shared fixture\n",
            "ue4ss/Mods/Example/Scripts/main.lua": b"-- example fixture\n",
        },
    )


def test_reviewed_code_mod_lifecycle(isolated, monkeypatch, tmp_path):
    sid = windows_server()
    archive = loader_archive(tmp_path)
    monkeypatch.setattr(code_mods, "cached_release", lambda *args, **kwargs: archive)
    code_mods.prepare_runtime(sid)
    win64 = ds.volume_path(sid) / "Pal/Binaries/Win64"
    assert (win64 / "dwmapi.dll").read_bytes() == b"proxy fixture"
    assert (win64 / "ue4ss/Mods/shared/UEHelpers/UEHelpers.lua").is_file()
    assert not (win64 / "ue4ss/Mods/Example").exists()

    monkeypatch.setattr(code_mods, "CATALOG", synthetic_catalog())
    package = write_zip(
        tmp_path / "reviewed.zip",
        {"Info.json": json.dumps({"PackageName": PACKAGE, "Version": "1.0.0"}), "Scripts/main.lua": SCRIPT},
    )
    mod = code_mods.install(sid, package, "reviewed.zip")
    assert mod["enabled"] is False
    assert mod["version"] == "1.0.0"
    live = win64 / "ue4ss/Mods"
    assert (live / PACKAGE / "Scripts/main.lua").read_bytes() == SCRIPT

    with pytest.raises(ValueError, match="Acknowledge"):
        code_mods.action(sid, mod["id"], "enable")
    code_mods.action(sid, mod["id"], "enable", True)
    assert (live / PACKAGE / "Scripts/main.lua").read_bytes() == SCRIPT
    assert (live / "mods.txt").read_text() == PACKAGE + " : 1\n"
    code_mods.verify(sid)
    code_mods.action(sid, mod["id"], "disable")
    assert (live / "mods.txt").read_text() == ""
    assert (live / PACKAGE / "Scripts/main.lua").read_bytes() == SCRIPT
    code_mods.action(sid, mod["id"], "remove")
    assert not (live / PACKAGE).exists()


def test_code_mod_rejects_unreviewed_or_altered_scripts(isolated, monkeypatch, tmp_path):
    sid = windows_server()
    archive = loader_archive(tmp_path)
    monkeypatch.setattr(code_mods, "cached_release", lambda *args, **kwargs: archive)
    code_mods.prepare_runtime(sid)
    monkeypatch.setattr(code_mods, "CATALOG", synthetic_catalog())
    altered = write_zip(tmp_path / "altered.zip", {"Scripts/main.lua": b"-- altered\n"})
    with pytest.raises(ValueError, match="reviewed"):
        code_mods.install(sid, altered, "altered.zip")
    with pytest.raises(ValueError, match="ZIP"):
        code_mods.install(sid, write_zip(tmp_path / "mod.rar", {"Scripts/main.lua": SCRIPT}), "mod.rar")


def test_loader_integrity_and_native_runtime_gate(isolated, monkeypatch, tmp_path, server):
    with pytest.raises(ValueError, match="runtime first"):
        code_mods.install(server, write_zip(tmp_path / "x.zip", {"Scripts/main.lua": SCRIPT}), "x.zip")
    assert code_mods.list_mods(server)["available"] is False

    sid = windows_server(port=18212)
    archive = loader_archive(tmp_path)
    monkeypatch.setattr(code_mods, "cached_release", lambda *args, **kwargs: archive)
    code_mods.prepare_runtime(sid)
    license_file = ds.volume_path(sid) / "Pal/Binaries/Win64/ue4ss/LICENSE"
    license_file.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Loader integrity"):
        code_mods.verify(sid)


def test_conversion_copies_world_and_returns_to_native(server):
    inst = ds.get_instance(server)
    inst["installed"] = True
    ds.save(inst)
    native = ds.volume_path(server)
    saved = native / "Pal/Saved/SaveGames/World.sav"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"native world fixture")

    prepared = ds.prepare_converted_runtime(server)
    inst = ds.get_instance(server)
    converted = ds.volume_path(server)
    assert prepared["files"] == 1
    assert prepared["data_dir"] == converted.name
    assert converted != native
    assert (converted / "Pal/Saved/SaveGames/World.sav").read_bytes() == b"native world fixture"
    assert saved.read_bytes() == b"native world fixture"
    assert inst["runtime"] == "windows-wine"
    assert inst["installed"] is False
    assert inst["previous_runtime"]["data_dir"] == native.name
    assert (ds.config.BACKUP_DIR / server / prepared["backup"]).is_file()
    assert ds.public(inst)["can_return_to_native"] is True

    with pytest.raises(ValueError, match="Type the server name"):
        ds.rollback_runtime(server, "wrong")
    ds.rollback_runtime(server, "test-world")
    inst = ds.get_instance(server)
    assert inst["runtime"] == "native-linux"
    assert inst["installed"] is True
    assert inst["data_dir"] == native.name
    assert "previous_runtime" not in inst
    assert converted.is_dir(), "the separate Windows installation is retained for inspection"


def test_conversion_requires_stopped_installed_native_server(server, isolated):
    with pytest.raises(ValueError, match="Install the native server"):
        ds.begin_convert(server, "test-world", True)
    inst = ds.get_instance(server)
    inst["installed"] = True
    ds.save(inst)
    with pytest.raises(ValueError, match="Type the server name"):
        ds.begin_convert(server, "wrong", True)
    with pytest.raises(ValueError, match="Acknowledge"):
        ds.begin_convert(server, "test-world", False)


def test_controller_code_mod_upload(controller, isolated, monkeypatch, tmp_path):
    sid = windows_server()
    archive = loader_archive(tmp_path)
    monkeypatch.setattr(code_mods, "cached_release", lambda *args, **kwargs: archive)
    code_mods.prepare_runtime(sid)
    monkeypatch.setattr(code_mods, "CATALOG", synthetic_catalog())
    package = write_zip(tmp_path / "upload.zip", {"Scripts/main.lua": SCRIPT})
    response = controller.post(
        f"/v1/servers/{sid}/code-mods/upload",
        content=package.read_bytes(),
        headers={"x-filename": "upload.zip", "content-type": "application/octet-stream"},
    )
    assert response.status_code == 201
    assert response.json()["package"] == PACKAGE
    listed = controller.get(f"/v1/servers/{sid}/code-mods").json()
    assert listed["loader_ready"] is True
    assert [m["package"] for m in listed["installed"]] == [PACKAGE]


def test_controller_exposes_code_mods_and_runtime_gate(controller, server):
    response = controller.get(f"/v1/servers/{server}/code-mods")
    assert response.status_code == 200
    assert response.json()["available"] is False
    response = controller.post(
        f"/v1/servers/{server}/runtime",
        json={"action": "convert", "confirmation": "wrong", "acknowledge_code_mods": True},
    )
    assert response.status_code == 409
