from __future__ import annotations

import sqlite3
from secrets import token_hex
from shutil import copyfile
from datetime import datetime
from pathlib import Path


REQUIRED_COLUMNS = {
    "users": {"id", "name", "emoji", "created_at"},
    "movies": {
        "id", "title", "original_title", "year", "genres", "overview", "runtime", "rating",
        "vote_count", "keywords", "director", "cast_names", "poster_path", "backdrop_path", "source",
    },
    "sessions": {
        "id", "session_date", "title", "status", "selected_movie_id", "recommendations",
        "rejected_movies", "created_at", "updated_at",
    },
    "watch_history": {"id", "session_id", "movie_id", "watched_at"},
    "feedback": {"history_id", "user_id", "rating", "created_at"},
}
REQUIRED_TABLES = set(REQUIRED_COLUMNS)
MAX_IMPORTED_BACKUP_BYTES = 64 * 1024 * 1024


def _backup_path(backup_dir: Path, name: str) -> Path:
    path = backup_dir / name
    if path.parent != backup_dir or path.suffix != ".db" or not path.is_file():
        raise ValueError("Копия не найдена")
    return path


def _validate_backup(path: Path) -> None:
    source: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {
            table: {row[1] for row in source.execute(f'PRAGMA table_info("{table}")')}
            for table in REQUIRED_TABLES.intersection(tables)
        }
    except sqlite3.Error as exc:
        raise ValueError("Файл не похож на копию Tonight") from exc
    finally:
        if source is not None:
            source.close()
    schema_is_compatible = REQUIRED_TABLES.issubset(tables) and all(
        required.issubset(columns.get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
    )
    if integrity != "ok" or not schema_is_compatible:
        raise ValueError("Файл не похож на копию Tonight")


def create_backup(database: Path, backup_dir: Path, *, prefix: str = "tonight") -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{prefix}-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    source = sqlite3.connect(database)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def list_backups(backup_dir: Path) -> list[dict[str, str | int]]:
    if not backup_dir.exists():
        return []
    backups = [path for path in backup_dir.glob("*.db") if path.is_file()]
    return [
        {"name": path.name, "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"), "bytes": path.stat().st_size}
        for path in sorted(backups, key=lambda item: item.stat().st_mtime, reverse=True)
    ]


def import_backup(backup_dir: Path, incoming: Path) -> Path:
    """Validate an uploaded copy before exposing it as a restorable local backup."""
    if not incoming.is_file() or incoming.stat().st_size == 0 or incoming.stat().st_size > MAX_IMPORTED_BACKUP_BYTES:
        raise ValueError("Файл копии слишком большой или пустой")
    backup_dir.mkdir(parents=True, exist_ok=True)
    staging = backup_dir / f".checking-import-{token_hex(8)}.db"
    target = backup_dir / f"imported-{datetime.now():%Y%m%d-%H%M%S}-{token_hex(4)}.db"
    try:
        copyfile(incoming, staging)
        _validate_backup(staging)
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)
    return target


def restore_backup(database: Path, backup_dir: Path, name: str) -> Path:
    source_path = _backup_path(backup_dir, name)
    _validate_backup(source_path)
    safety = create_backup(database, backup_dir, prefix="before-restore")
    source = sqlite3.connect(source_path)
    try:
        destination = sqlite3.connect(database)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return safety
