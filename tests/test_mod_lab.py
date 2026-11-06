"""Lab-only code packages must match reviewed hashes, without bundling third-party Lua."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def package(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/wine-mod-smoke.py"
    spec = importlib.util.spec_from_file_location("wine_mod_lab", path)
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    source = tmp_path / "package"
    (source / "Scripts").mkdir(parents=True)
    script = b"-- synthetic non-executed test fixture\n"
    (source / "Scripts/main.lua").write_bytes(script)
    (source / "Info.json").write_text(json.dumps({"PackageName": "BaseRadiusImproved", "Version": "1.2.2"}))
    monkeypatch.setattr(lab, "BASE_RADIUS_FILES", {"main.lua": hashlib.sha256(script).hexdigest()})
    return lab, source


def test_lab_package_requires_reviewed_bytes(package):
    lab, source = package
    assert lab.validate_base_radius(source) == source
    (source / "Scripts/main.lua").write_text("-- altered fixture")
    with pytest.raises(ValueError, match="checksum"):
        lab.validate_base_radius(source)


def test_lab_rejects_unreviewed_version_and_incomplete_package(package):
    lab, source = package
    (source / "Info.json").write_text(json.dumps({"PackageName": "BaseRadiusImproved", "Version": "9.0.0"}))
    with pytest.raises(ValueError, match="reviewed"):
        lab.validate_base_radius(source)
    (source / "Scripts/main.lua").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        lab.validate_base_radius(source)


def test_lab_rejects_extra_executable_and_symlink(package, tmp_path):
    lab, source = package
    (source / "Scripts/extra.dll").write_bytes(b"MZ fixture")
    with pytest.raises(ValueError, match="Unexpected"):
        lab.validate_base_radius(source)
    (source / "Scripts/extra.dll").unlink()
    target = tmp_path / "outside.lua"
    target.write_text("-- external")
    (source / "Scripts/main.lua").unlink()
    (source / "Scripts/main.lua").symlink_to(target)
    with pytest.raises(ValueError, match="Symlinks"):
        lab.validate_base_radius(source)


def test_lab_does_not_toggle_mods_while_active(package, tmp_path):
    lab, _ = package
    root = tmp_path / "run"
    root.mkdir()
    run = lab.Lab(root, None)
    (root / "active-container-id").write_text("synthetic-test-container")
    with pytest.raises(RuntimeError, match="Stop"):
        run.set_base_radius_enabled(False)
