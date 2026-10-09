"""Safe local application-package updates for the portable Tonight release."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from backend.backups import create_backup


MANIFEST_NAME = "tonight-release.json"
RELEASE_FORMAT = 1
APP_VERSION = "1.6.6"
PRESERVED_NAMES = {".env", ".venv", "data", "outputs", "work", "rollback", "updates", ".pytest_cache", "__pycache__", ".tonight-update.lock", "catalogupdates", "catalogdownloads"}
MAX_RELEASE_FILES = 10_000
MAX_RELEASE_BYTES = 500 * 1024 * 1024
PORTABLE_PUBLIC_FILES = ("Tonight.exe", "Обновить Tonight.exe", ".env.example", "README.txt", "PRIVACY.txt")


class ReleaseError(ValueError):
    """A local file is not a safe Tonight update package."""


class RecoveryError(ReleaseError):
    """Program restoration failed; never restart the possibly partial application."""


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def _checked_target(root: Path, name: str) -> Path:
    return _checked_path(root, _safe_relative(name))


def _checked_path(root: Path, relative: Path) -> Path:
    target = root / relative
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if _is_link(candidate):
            raise ReleaseError("Обновление не может изменять файлы через ссылки-папки")
    if not target.resolve().is_relative_to(root):
        raise ReleaseError("Путь обновления выходит за папку Tonight")
    return target


def _atomic_copy(source: Path, target: Path, *, restoring: bool = False) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = ".tonight-restore-" if restoring else ".tonight-new-"
    handle, name = tempfile.mkstemp(prefix=prefix, dir=target.parent)
    os.close(handle)
    sibling = Path(name)
    try:
        shutil.copy2(source, sibling)
        os.replace(sibling, target)
    finally:
        sibling.unlink(missing_ok=True)


def _restore_changed(root: Path, snapshot: Path, changed: list[str]) -> None:
    failed = False
    for name in reversed(changed):
        try:
            previous, target = snapshot / name, root / name
            if previous.is_file():
                _atomic_copy(previous, target, restoring=True)
            else:
                target.unlink(missing_ok=True)
        except OSError:
            failed = True
    if failed:
        raise RecoveryError("Не удалось восстановить все файлы Tonight. Не запускайте программу; сохранённая версия находится в rollback. Личные данные не изменены.")


@dataclass(frozen=True)
class Release:
    version: str
    files: tuple[str, ...]


def _safe_relative(name: str) -> Path:
    if any(character in name for character in '\\:*?"<>|') or any(ord(character) < 32 for character in name):
        raise ReleaseError("Пакет содержит небезопасный путь")
    posix = PurePosixPath(name)
    if not name or posix.is_absolute() or ".." in posix.parts or len(posix.parts) == 0:
        raise ReleaseError("Пакет содержит небезопасный путь")
    if any(part.casefold() in PRESERVED_NAMES for part in posix.parts):
        raise ReleaseError("Пакет пытается заменить личные данные")
    devices = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(part.endswith((".", " ")) or part.split(".")[0].casefold() in devices for part in posix.parts):
        raise ReleaseError("Пакет содержит небезопасный путь Windows")
    if name != posix.as_posix():
        raise ReleaseError("Пакет содержит неоднозначный путь")
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
    if any(not isinstance(item, str) for item in files) or len(files) != len({item.casefold() for item in files}):
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
        if item.name.casefold() in PRESERVED_NAMES:
            continue
        if _is_link(item) or (item.is_dir() and any(_is_link(path) for path in item.rglob("*"))):
            raise ReleaseError("Сначала перенесите Tonight в обычную папку без ссылок-папок")
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


def create_portable_archive(root: Path, archive: Path) -> Path:
    """Create a distributable portable ZIP without runtime data or secrets.

    The archive deliberately uses a small allowlist instead of copying the
    whole portable folder: ``data/`` and ``.env`` can contain personal data and
    credentials, while ``catalog/`` is produced by ``stage_catalog_bundle``.
    """
    root = root.resolve()
    files = list(PORTABLE_PUBLIC_FILES)
    for name in PORTABLE_PUBLIC_FILES:
        if not (root / name).is_file():
            raise ReleaseError(f"Не найден файл для переносимого архива: {name}")
    catalog = root / "catalog"
    if not (catalog / "tonight.db").is_file():
        raise ReleaseError("В переносимом архиве нет каталога фильмов")
    files.extend(path.relative_to(root).as_posix() for path in catalog.rglob("*") if path.is_file())
    safe_files = tuple(sorted(str(_safe_relative(name).as_posix()) for name in files))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in safe_files:
            bundle.write(root / name, name)
    return archive


def apply_release(root: Path, archive: Path, *, backup: Callable[[Path], object] | None = None) -> Release:
    """Install a validated local update while leaving user-owned paths untouched."""
    root = root.resolve()
    release = read_release(archive)
    root.mkdir(parents=True, exist_ok=True)
    for name in release.files:
        _checked_target(root, name)
    _checked_path(root, Path("rollback/previous"))
    with tempfile.TemporaryDirectory(prefix="tonight-install-stage-") as temporary:
        stage = Path(temporary)
        try:
            with zipfile.ZipFile(archive) as bundle:
                for name in release.files:
                    staged = stage / name
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(name) as source, staged.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise ReleaseError("Архив обновления повреждён") from exc
        (backup or _default_backup)(root)
        rollback = root / "rollback" / "previous"
        _copy_application(root, rollback)
        changed: list[str] = []
        try:
            for name in release.files:
                target = root / name
                _atomic_copy(stage / name, target)
                changed.append(name)
            manifest = {"product": "Tonight", "format": RELEASE_FORMAT, "version": release.version, "files": list(release.files)}
            (stage / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _atomic_copy(stage / MANIFEST_NAME, root / MANIFEST_NAME)
            changed.append(MANIFEST_NAME)
        except OSError:
            _restore_changed(root, rollback, changed)
            raise
    return release


def _current_managed_files(root: Path) -> list[str]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files", []) if isinstance(manifest, dict) else []
    except json.JSONDecodeError:
        files = []
    names = []
    for item in files:
        if not isinstance(item, str):
            continue
        try:
            relative = _safe_relative(item)
        except ReleaseError:
            continue
        names.append(relative.as_posix())
    return names


def rollback_previous(root: Path) -> None:
    """Restore the last program-file snapshot without replacing data or .env."""
    root = root.resolve()
    previous = root / "rollback" / "previous"
    _checked_path(root, Path("rollback/previous"))
    if not previous.is_dir():
        raise ReleaseError("Предыдущая версия Tonight не найдена")
    old_files = sorted(path.relative_to(previous).as_posix() for path in previous.rglob("*")
                       if path.is_file() and path.relative_to(previous).parts[0].casefold() not in PRESERVED_NAMES)
    names = set(old_files) | set(_current_managed_files(root)) | {MANIFEST_NAME}
    for name in names:
        _checked_target(root, name)
        _checked_target(previous, name)
    # Preserve the current version until the entire rollback succeeds. Keep this
    # recovery directory if restoring it fails too, rather than deleting evidence.
    snapshot = Path(tempfile.mkdtemp(prefix="restore-current-", dir=root / "rollback"))
    changed: list[str] = []
    recovery_failed = False
    try:
        for name in names:
            if (root / name).is_file():
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / name, destination)
        try:
            for name in old_files:
                _atomic_copy(previous / name, root / name)
                changed.append(name)
            for name in sorted(names - set(old_files)):
                (root / name).unlink(missing_ok=True)
                changed.append(name)
        except OSError:
            try:
                _restore_changed(root, snapshot, changed)
            except RecoveryError:
                recovery_failed = True
                raise
            raise
    finally:
        if not recovery_failed:
            shutil.rmtree(snapshot)
