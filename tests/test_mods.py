import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from app import docker_service as ds
from app import mods
from app.archives import extract_zip

PAK = b"synthetic asset fixture, not a playable mod" + b"\xe1\x12\x6f\x5a" + os.urandom(32)


def archive(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for key, value in entries:
            z.writestr(key, value)
    return path


def package(tmp_path, name="test.zip", content=PAK, filename="Test.pak", metadata=None):
    entries = [(filename, content)]
    if metadata:
        entries.append(("gamehub-mod.json", json.dumps(metadata)))
    return archive(tmp_path / name, entries)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.pak",
        "/tmp/evil.pak",
        "a/../../x.pak",
        "C:/evil.pak",
        "a\\evil.pak",
        "a/./x.pak",
        "a//x.pak",
    ],
)
def test_archive_paths_rejected(tmp_path, name):
    source = archive(tmp_path / "bad.zip", [(name, PAK)])
    with pytest.raises(ValueError):
        extract_zip(source, tmp_path / "stage", 1024**2, 20)
    assert not (tmp_path / "escape.pak").exists()


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR])
def test_archive_special_files_rejected(tmp_path, kind):
    info = zipfile.ZipInfo("evil.pak")
    info.create_system = 3
    info.external_attr = (kind | 0o777) << 16
    source = archive(tmp_path / "bad.zip", [(info, b"/etc/passwd")])
    with pytest.raises(ValueError):
        extract_zip(source, tmp_path / "stage", 1024**2, 20)


def test_size_count_duplicate_and_crc_limits(tmp_path):
    source = archive(tmp_path / "bad.zip", [("a.pak", PAK), ("A.pak", PAK)])
    with pytest.raises(ValueError, match="Duplicate"):
        extract_zip(source, tmp_path / "stage", 1024**2, 20)
    with pytest.raises(ValueError, match="entries"):
        extract_zip(source, tmp_path / "stage", 1024**2, 1)
    source = archive(tmp_path / "size.zip", [("a.pak", b"a" * 100)])
    with pytest.raises(ValueError, match="size"):
        extract_zip(source, tmp_path / "stage", 50, 20)
    data = bytearray(source.read_bytes())
    start = data.find(b"a" * 100)
    data[start] = 98
    source.write_bytes(data)
    with pytest.raises(zipfile.BadZipFile):
        extract_zip(source, tmp_path / "stage", 1000, 20)


def test_compression_bomb(tmp_path):
    source = tmp_path / "bomb.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.pak", b"0" * 1024**2)
    with pytest.raises(ValueError, match="compression"):
        extract_zip(source, tmp_path / "stage", 2 * 1024**2, 20)


def test_install_enable_disable_and_remove(server, tmp_path):
    source = package(tmp_path)
    m = mods.install(server, source, "test.zip")
    assert m["enabled"] is False
    assert not (mods.mods_dir(server) / "Test.pak").exists()
    with pytest.raises(ValueError, match="Acknowledge"):
        mods.action(server, m["id"], "enable")
    mods.action(server, m["id"], "enable", True)
    assert (mods.mods_dir(server) / "Test.pak").read_bytes() == PAK
    mods.action(server, m["id"], "disable")
    assert not (mods.mods_dir(server) / "Test.pak").exists()
    assert (mods.library(server) / m["id"] / m["revision"] / "Test.pak").exists()
    mods.action(server, m["id"], "remove")
    assert mods.list_mods(server)["installed"] == []


def test_duplicate_and_conflict_no_overwrite(server, tmp_path):
    m = mods.install(server, package(tmp_path), "test.zip")
    with pytest.raises(ValueError, match="already installed"):
        mods.install(server, tmp_path / "test.zip", "test.zip")
    mods.action(server, m["id"], "enable", True)
    other = mods.install(server, package(tmp_path, "other.zip", PAK + b"new"), "other.zip")
    with pytest.raises(ValueError, match="Conflicting"):
        mods.action(server, other["id"], "enable", True)
    assert (mods.mods_dir(server) / "Test.pak").read_bytes() == PAK
    assert not next(m for m in mods.state(server)["mods"] if m["id"] == other["id"])["enabled"]


def test_update_and_rollback(server, tmp_path):
    m = mods.install(server, package(tmp_path), "test.zip")
    mods.action(server, m["id"], "enable", True)
    source = package(tmp_path, "update.zip", PAK + b"update", metadata={"name": "Updated", "version": "2"})
    new = mods.install(server, source, "update.zip", m["id"])
    assert new["version"] == "2"
    assert (mods.mods_dir(server) / "Test.pak").read_bytes() == PAK + b"update"
    mods.action(server, m["id"], "rollback")
    assert (mods.mods_dir(server) / "Test.pak").read_bytes() == PAK


def test_invalid_update_preserves_existing_mod(server, tmp_path):
    m = mods.install(server, package(tmp_path), "test.zip")
    mods.action(server, m["id"], "enable", True)
    with pytest.raises(ValueError):
        mods.install(
            server, package(tmp_path, "update.zip", b"MZevil", filename="evil.dll"), "update.zip", m["id"]
        )
    assert (mods.mods_dir(server) / "Test.pak").read_bytes() == PAK
    assert len(mods.state(server)["mods"]) == 1


def test_dependencies_and_companions(server, tmp_path):
    base = mods.install(server, package(tmp_path), "test.zip")
    dependent = mods.install(
        server,
        package(
            tmp_path, "dep.zip", PAK + b"dep", filename="Dep.pak", metadata={"dependencies": [base["id"]]}
        ),
        "dep.zip",
    )
    with pytest.raises(ValueError, match="dependency"):
        mods.action(server, dependent["id"], "enable", True)
    with pytest.raises(ValueError, match="depends"):
        mods.action(server, base["id"], "remove")
    with pytest.raises(ValueError, match="companions"):
        mods.install(
            server,
            package(tmp_path, "toc.zip", b"-==--==--==--==-" + b"data", filename="Test.utoc"),
            "toc.zip",
        )


def test_interrupted_mod_swap_recovers(server, tmp_path):
    m = mods.install(server, package(tmp_path), "test.zip")
    live = mods.mods_dir(server)
    old = live.parent / ".gamehub-mods-old"
    live.rename(old)
    assert not live.exists()
    mods.recover(server)
    assert mods.state(server)["mods"][0]["id"] == m["id"]


def test_modified_manifest_rejected(server, tmp_path):
    mods.install(server, package(tmp_path), "test.zip")
    (mods.mods_dir(server) / mods.STATE).write_text('{"state":{"mods":[]},"signature":"bad"}')
    with pytest.raises(ValueError, match="integrity"):
        mods.list_mods(server)


def test_running_server_blocks_file_mutation(server, tmp_path):
    cont = ds.ensure_container(server)
    cont.start()
    with pytest.raises(ValueError, match="Stop"):
        mods.install(server, package(tmp_path), "test.zip")


def test_unmanaged_mod_directory_and_symlinks_rejected(server, tmp_path):
    live = mods.mods_dir(server)
    live.mkdir()
    with pytest.raises(ValueError, match="unmanaged"):
        mods.install(server, package(tmp_path), "test.zip")
    live.rmdir()
    live.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        mods.list_mods(server)


def test_failed_directory_publication_restores_previous_tree(server, tmp_path, monkeypatch):
    m = mods.install(server, package(tmp_path), "test.zip")
    mods.action(server, m["id"], "enable", True)
    replace = os.replace

    def fail_new_tree(source, destination):
        if Path(source).name == ".gamehub-mods-next":
            raise OSError("disposable rename failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_new_tree)
    with pytest.raises(OSError, match="rename failure"):
        mods.install(server, package(tmp_path, "failed.zip", PAK + b"new"), "failed.zip", m["id"])
    assert (mods.mods_dir(server) / "Test.pak").read_bytes() == PAK
    assert mods.state(server)["mods"][0]["revision"] == m["revision"]
