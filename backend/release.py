"""Safe local application-package updates for the portable Tonight release."""
from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from backend.backups import create_backup


MANIFEST_NAME = "tonight-release.json"
RELEASE_FORMAT = 1
APP_VERSION = "1.6.4"
PRESERVED_NAMES = {".env", ".venv", "data", "outputs", "work", "rollback", ".pytest_cache", "__pycache__"}
MAX_RELEASE_FILES = 10_000
MAX_RELEASE_BYTES = 500 * 1024 * 1024


class ReleaseError(ValueError):
    """A local file is not a safe Tonight update package."""


@dataclass(frozen=True)
class Release:
    version: str
    files: tuple[str, ...]


def _safe_relative(name: str) -> Path:
    if "\\" in name or ":" in name:
        raise ReleaseError("Пакет содержит небезопасный путь")
    posix = PurePosixPath(name)
    if not name or posix.is_absolute() or ".." in posix.parts or len(posix.parts) == 0:
        raise ReleaseError("Пакет содержит небезопасный путь")
    if posix.parts[0] in PRESERVED_NAMES:
        raise ReleaseError("Пакет пытается заменить личные данные")
    return Path(*posix.parts)


def read_release(archive: Path) -> Release:
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = [entry.filename for entry in bundle.infolist() if not entry.is_dir()]
            if MANIFEST_NAME not in names:
                raise ReleaseError("В пакете нет манифеста Tonight")
            if len(names) > MAX_RELEASE_FILES or sum(item.file_size for item in bundle.infolist()) > MAX_RELEASE_BYTES:
                raise ReleaseError("Пакет Tonight слишком большой")
            try:
                manifest = json.loads(bundle.read(MANIFEST_NAME))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ReleaseError("Манифест Tonight не читается") from exc
    except zipfile.BadZipFile as exc:
        raise ReleaseError("Выберите корректный пакет Tonight (.zip)") from exc

    if not isinstance(manifest, dict) or manifest.get("product") != "Tonight" or manifest.get("format") != RELEASE_FORMAT:
        raise ReleaseError("Пакет не предназначен для Tonight")
    version = manifest.get("version")
    files = manifest.get("files")
    if not isinstance(version, str) or not version.strip() or not isinstance(files, list) or not files:
        raise ReleaseError("В манифесте Tonight не хватает версии или файлов")
    if any(not isinstance(item, str) for item in files) or len(files) != len(set(files)):
        raise ReleaseError("Манифест Tonight содержит повторяющиеся файлы")
    safe_files = tuple(sorted(str(_safe_relative(item).as_posix()) for item in files))
    archived_files = sorted(name for name in names if name != MANIFEST_NAME)
    if archived_files != list(safe_files):
        raise ReleaseError("Состав пакета не совпадает с манифестом")
    return Release(version=version.strip(), files=safe_files)


def _copy_application(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in PRESERVED_NAMES:
            continue
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)


def _default_backup(root: Path) -> Path | None:
    database = root / "data" / "tonight.db"
    if not database.exists():
        return None
    return create_backup(database, root / "data" / "backups", prefix="before-update")


def create_release_archive(root: Path, archive: Path, *, version: str, files: list[str]) -> Path:
    """Create a local Tonight update package from explicitly selected files."""
    if not version.strip() or not files:
        raise ReleaseError("Для пакета Tonight нужны версия и файлы")
    if len(files) != len(set(files)):
        raise ReleaseError("В пакете Tonight повторяются файлы")
    safe_files = tuple(sorted(str(_safe_relative(item).as_posix()) for item in files))
    root = root.resolve()
    for name in safe_files:
        if not (root / name).is_file():
            raise ReleaseError(f"Не найден файл для пакета: {name}")
    manifest = {"product": "Tonight", "format": RELEASE_FORMAT, "version": version.strip(), "files": list(safe_files)}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for name in safe_files:
            bundle.write(root / name, name)
    return archive


def apply_release(root: Path, archive: Path, *, backup: Callable[[Path], object] | None = None) -> Release:
    """Install a validated local update while leaving user-owned paths untouched."""
    root = root.resolve()
    release = read_release(archive)
    root.mkdir(parents=True, exist_ok=True)
    (backup or _default_backup)(root)

    rollback = root / "rollback" / "previous"
    _copy_application(root, rollback)
    with zipfile.ZipFile(archive) as bundle:
        for name in release.files:
            target = root / _safe_relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(name) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    manifest = {"product": "Tonight", "format": RELEASE_FORMAT, "version": release.version, "files": list(release.files)}
    (root / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return release


def _remove_current_managed_files(root: Path) -> None:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files", []) if isinstance(manifest, dict) else []
    except json.JSONDecodeError:
        files = []
    for item in files:
        if not isinstance(item, str):
            continue
        try:
            target = root / _safe_relative(item)
        except ReleaseError:
            continue
        if target.is_file():
            target.unlink()
    manifest_path.unlink(missing_ok=True)


def rollback_previous(root: Path) -> None:
    """Restore the last program-file snapshot without replacing data or .env."""
    root = root.resolve()
    previous = root / "rollback" / "previous"
    if not previous.is_dir():
        raise ReleaseError("Предыдущая версия Tonight не найдена")
    _remove_current_managed_files(root)
    for item in previous.iterdir():
        if item.name in PRESERVED_NAMES:
            continue
        target = root / item.name
        if item.is_dir():
            if target.exists():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
