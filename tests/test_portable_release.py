from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import backend.release as release_module

from backend.release import ReleaseError, apply_release, create_portable_archive, create_release_archive, read_release, rollback_previous


def _archive(path: Path, *, version: str = "1.5.0", files: dict[str, str] | None = None) -> Path:
    files = files or {"frontend/app.js": "new interface", "launcher.py": "new launcher"}
    manifest = {"product": "Tonight", "format": 1, "version": version, "files": sorted(files)}
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("tonight-release.json", json.dumps(manifest))
        for name, content in files.items():
            bundle.writestr(name, content)
    return path


def test_update_preserves_user_data_and_creates_safety_copies(tmp_path: Path):
    root = tmp_path / "Tonight"
    (root / "frontend").mkdir(parents=True)
    (root / "frontend" / "app.js").write_text("old interface", encoding="utf-8")
    (root / "launcher.py").write_text("old launcher", encoding="utf-8")
    (root / ".env").write_text("TOKEN=private", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "keep.txt").write_text("runtime", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "tonight.db").write_bytes(b"not-a-real-db")
    events: list[str] = []

    result = apply_release(root, _archive(tmp_path / "Tonight-update-1.5.0.zip"), backup=lambda _: events.append("backup"))

    assert result.version == "1.5.0"
    assert events == ["backup"]
    assert (root / "frontend" / "app.js").read_text(encoding="utf-8") == "new interface"
    assert (root / ".env").read_text(encoding="utf-8") == "TOKEN=private"
    assert (root / ".venv" / "keep.txt").read_text(encoding="utf-8") == "runtime"
    assert (root / "data" / "tonight.db").read_bytes() == b"not-a-real-db"
    assert (root / "rollback" / "previous" / "frontend" / "app.js").read_text(encoding="utf-8") == "old interface"


def test_rollback_restores_previous_program_without_touching_data(tmp_path: Path):
    root = tmp_path / "Tonight"
    (root / "frontend").mkdir(parents=True)
    (root / "frontend" / "app.js").write_text("old", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "tonight.db").write_bytes(b"history")
    apply_release(root, _archive(tmp_path / "Tonight-update.zip", files={"frontend/app.js": "new"}), backup=lambda _: None)

    rollback_previous(root)

    assert (root / "frontend" / "app.js").read_text(encoding="utf-8") == "old"
    assert (root / "data" / "tonight.db").read_bytes() == b"history"


def test_rejects_archive_with_path_outside_program_folder(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("tonight-release.json", json.dumps({"product": "Tonight", "format": 1, "version": "1.5.0", "files": ["../evil.py"]}))
        bundle.writestr("../evil.py", "no")

    with pytest.raises(ReleaseError, match="безопас"):
        apply_release(tmp_path / "Tonight", archive, backup=lambda _: None)


def test_rejects_windows_style_path_outside_program_folder(tmp_path: Path):
    archive = tmp_path / "unsafe-windows.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("tonight-release.json", json.dumps({"product": "Tonight", "format": 1, "version": "1.5.0", "files": ["..\\evil.py"]}))
        bundle.writestr("..\\evil.py", "no")

    with pytest.raises(ReleaseError, match="безопас"):
        apply_release(tmp_path / "Tonight", archive, backup=lambda _: None)


def test_rejects_windows_drive_style_path(tmp_path: Path):
    archive = tmp_path / "unsafe-drive.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("tonight-release.json", json.dumps({"product": "Tonight", "format": 1, "version": "1.5.0", "files": ["C:/evil.py"]}))
        bundle.writestr("C:/evil.py", "no")

    with pytest.raises(ReleaseError, match="безопас"):
        apply_release(tmp_path / "Tonight", archive, backup=lambda _: None)


def test_release_builder_writes_a_valid_manifested_archive(tmp_path: Path):
    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / "Tonight.exe").write_bytes(b"binary")

    archive = create_release_archive(portable, tmp_path / "Tonight-update-1.5.0.zip", version="1.5.0", files=["Tonight.exe"])

    assert read_release(archive).version == "1.5.0"


def test_public_portable_archive_includes_only_program_and_catalog(tmp_path: Path):
    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / "Tonight.exe").write_bytes(b"binary")
    (portable / "Обновить Tonight.exe").write_bytes(b"updater")
    (portable / ".env.example").write_text("TMDB_READ_TOKEN=", encoding="utf-8")
    (portable / "README.txt").write_text("readme", encoding="utf-8")
    (portable / "PRIVACY.txt").write_text("privacy", encoding="utf-8")
    (portable / ".env").write_text("TOKEN=private", encoding="utf-8")
    (portable / "data").mkdir()
    (portable / "data" / "tonight.db").write_bytes(b"personal history")
    (portable / "catalog" / "posters").mkdir(parents=True)
    (portable / "catalog" / "tonight.db").write_bytes(b"catalog only")
    (portable / "catalog" / "posters" / "movie.jpg").write_bytes(b"poster")

    archive = create_portable_archive(portable, tmp_path / "Tonight-portable.zip")

    with zipfile.ZipFile(archive) as bundle:
        names = sorted(entry.filename for entry in bundle.infolist() if not entry.is_dir())
        template = bundle.read(".env.example").decode("utf-8")
    assert names == [
        ".env.example",
        "PRIVACY.txt",
        "README.txt",
        "Tonight.exe",
        "catalog/posters/movie.jpg",
        "catalog/tonight.db",
        "Обновить Tonight.exe",
    ]
    token_line = next(line for line in template.splitlines() if line.startswith("TMDB_READ_TOKEN="))
    assert token_line == "TMDB_READ_TOKEN="


@pytest.mark.parametrize("name", ["DATA/tonight.db", ".ENV", "catalog/../.env", "catalog/posters/.env", "Tonight.exe.", "CON", "frontend/aux.js"])
def test_rejects_windows_aliases_and_private_paths(tmp_path, name):
    with pytest.raises(ReleaseError):
        apply_release(tmp_path / "Tonight", _archive(tmp_path / "bad.zip", files={name: "private"}), backup=lambda _: None)


def test_partial_install_failure_restores_previous_program_and_removes_new_files(tmp_path, monkeypatch):
    root = tmp_path / "Tonight"; root.mkdir()
    (root / "launcher.py").write_text("old", encoding="utf-8")
    (root / ".env").write_text("private", encoding="utf-8")
    archive = _archive(tmp_path / "Tonight-update.zip", files={"aaa-new.txt": "new", "launcher.py": "new"})
    original_replace = release_module.os.replace
    def fail_one(source, destination):
        if Path(destination) == root / "launcher.py" and Path(source).name.startswith(".tonight-new-"):
            raise OSError("simulated disk error")
        return original_replace(source, destination)
    monkeypatch.setattr(release_module.os, "replace", fail_one)
    with pytest.raises(OSError): apply_release(root, archive, backup=lambda _: None)
    assert (root / "launcher.py").read_text() == "old"
    assert (root / ".env").read_text() == "private"
    assert not (root / "aaa-new.txt").exists()
    assert not (root / "tonight-release.json").exists()


def test_corrupt_package_is_rejected_before_backup_or_program_changes(tmp_path):
    root = tmp_path / "Tonight"; root.mkdir()
    (root / "launcher.py").write_text("old", encoding="utf-8")
    archive = _archive(tmp_path / "Tonight-update.zip", files={"launcher.py": "new program"})
    archive.write_bytes(archive.read_bytes().replace(b"new program", b"bad program"))
    backups = []
    with pytest.raises(ReleaseError): apply_release(root, archive, backup=lambda _: backups.append(True))
    assert backups == [] and (root / "launcher.py").read_text() == "old"


def test_update_keeps_downloaded_packages_out_of_program_snapshot(tmp_path):
    root = tmp_path / "Tonight"; (root / "Updates").mkdir(parents=True)
    (root / "Updates" / "saved.zip").write_bytes(b"downloaded package")
    apply_release(root, _archive(tmp_path / "update.zip"), backup=lambda _: None)
    assert (root / "Updates" / "saved.zip").read_bytes() == b"downloaded package"
    assert not (root / "rollback" / "previous" / "Updates").exists()


def test_manual_rollback_failure_keeps_current_working_version(tmp_path, monkeypatch):
    root = tmp_path / "Tonight"; root.mkdir()
    (root / "launcher.py").write_text("old")
    (root / "other.py").write_text("old other")
    apply_release(root, _archive(tmp_path / "update.zip", files={"launcher.py": "new", "other.py": "new other"}), backup=lambda _: None)
    original = release_module.os.replace
    def fail_once(source, destination):
        if Path(destination) == root / "other.py" and Path(source).name.startswith(".tonight-new-"):
            raise OSError("simulated rollback error")
        return original(source, destination)
    monkeypatch.setattr(release_module.os, "replace", fail_once)
    with pytest.raises(OSError): rollback_previous(root)
    assert (root / "launcher.py").read_text() == "new"
    assert (root / "other.py").read_text() == "new other"
    assert (root / "tonight-release.json").is_file()


def test_failed_recovery_has_explicit_error_and_keeps_snapshot(tmp_path, monkeypatch):
    from backend.release import RecoveryError
    root = tmp_path / "Tonight"; root.mkdir()
    (root / "aaa.py").write_text("old a")
    (root / "zzz.py").write_text("old z")
    original = release_module.os.replace
    def fail(source, destination):
        if Path(destination) == root / "zzz.py" or Path(source).name.startswith(".tonight-restore-"):
            raise OSError("disk unavailable")
        return original(source, destination)
    monkeypatch.setattr(release_module.os, "replace", fail)
    with pytest.raises(RecoveryError):
        apply_release(root, _archive(tmp_path / "update.zip", files={"aaa.py": "new a", "zzz.py": "new z"}), backup=lambda _: None)
    assert (root / "rollback" / "previous" / "aaa.py").read_text() == "old a"


def test_junction_cannot_redirect_application_update_into_user_data(tmp_path):
    import os
    import subprocess
    root = tmp_path / "Tonight"; (root / "data").mkdir(parents=True)
    (root / "data" / "keep.txt").write_text("personal")
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "catalog"), str(root / "data")], capture_output=True)
        assert result.returncode == 0
    else:
        (root / "catalog").symlink_to(root / "data", target_is_directory=True)
    with pytest.raises(ReleaseError):
        apply_release(root, _archive(tmp_path / "update.zip", files={"catalog/keep.txt": "overwrite"}), backup=lambda _: None)
    assert (root / "data" / "keep.txt").read_text() == "personal"
