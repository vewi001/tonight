from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from backend.release import ReleaseError, apply_release, create_release_archive, read_release, rollback_previous


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
