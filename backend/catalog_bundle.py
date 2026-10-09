"""Bootstrap a portable install from a privacy-safe bundled movie catalog."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from backend.database.db import connect, db_session, initialize


def _movie_columns(database: Path) -> list[str]:
    db = sqlite3.connect(database)
    try:
        return [row[1] for row in db.execute("PRAGMA table_info(movies)")]
    finally:
        db.close()


def build_catalog_seed(source: Path, destination: Path) -> None:
    """Create a distributable database containing movie metadata only."""
    if not source.is_file():
        raise ValueError("Не найден каталог фильмов для переносимой сборки")
    destination.parent.mkdir(parents=True, exist_ok=True)
    initialize(destination)
    source_db = sqlite3.connect(source)
    source_db.row_factory = sqlite3.Row
    try:
        target_columns = _movie_columns(destination)
        source_columns = {row[1] for row in source_db.execute("PRAGMA table_info(movies)")}
        columns = [column for column in target_columns if column in source_columns]
        rows = source_db.execute(f"SELECT {','.join(columns)} FROM movies").fetchall()
    finally:
        source_db.close()
    with db_session(destination) as target:
        for row in rows:
            values = [None if column in {"poster_path", "backdrop_path"} else row[column] for column in columns]
            target.execute(
                f"INSERT OR REPLACE INTO movies({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                values,
            )
        # initialize() creates the two normal Tonight profiles. A distributable
        # catalog must contain no people, history, preferences, or sessions.
        for table in (
            "participants", "swipes", "swipe_decks", "watch_history", "feedback", "evening_feedback",
            "watchlist", "weekly_picks", "avoid_similar", "taste_genre_exclusions", "taste_profile_resets",
            "sessions", "users", "app_meta",
        ):
            target.execute(f"DELETE FROM {table}")
    # The portable ZIP carries only tonight.db, not SQLite's sidecar WAL file.
    # Merge pending writes and switch this immutable seed back to a single-file
    # journal mode before it is copied into the archive.
    checkpoint = sqlite3.connect(destination)
    try:
        checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        checkpoint.execute("PRAGMA journal_mode=DELETE")
    finally:
        checkpoint.close()


def _copy_missing_media(source: Path, destination: Path) -> int:
    if not source.is_dir():
        return 0
    copied = 0
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if not item.is_file():
            continue
        target = destination / item.name
        if target.exists():
            continue
        shutil.copy2(item, target)
        copied += 1
    return copied


def stage_catalog_bundle(source_data: Path, destination: Path) -> dict[str, int]:
    """Prepare the catalog-only files that are allowed inside a portable release."""
    source_data = source_data.resolve()
    source_database = source_data / "tonight.db"
    build_catalog_seed(source_database, destination / "tonight.db")
    posters = _copy_missing_media(source_data / "posters", destination / "posters")
    backdrops = _copy_missing_media(source_data / "backdrops", destination / "backdrops")
    with sqlite3.connect(destination / "tonight.db") as db:
        movies = db.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    return {"movies": movies, "media": posters + backdrops}


def bootstrap_catalog(root: Path, *, database: Path | None = None) -> dict[str, int]:
    """Merge the bundled catalog into user data, preserving all personal tables."""
    root = root.resolve()
    bundle = root / "catalog" / "tonight.db"
    database = database or root / "data" / "tonight.db"
    if not bundle.is_file():
        return {"movies": 0, "media": 0}
    initialize(database)
    source_db = sqlite3.connect(bundle)
    source_db.row_factory = sqlite3.Row
    try:
        target_columns = _movie_columns(database)
        source_columns = {row[1] for row in source_db.execute("PRAGMA table_info(movies)")}
        columns = [column for column in target_columns if column in source_columns]
        rows = source_db.execute(f"SELECT {','.join(columns)} FROM movies").fetchall()
    finally:
        source_db.close()
    mutable = [column for column in columns if column != "id"]
    assignments = ",".join(f"{column}=COALESCE(movies.{column},excluded.{column})" for column in mutable)
    with connect(database) as target:
        for row in rows:
            values = [None if column in {"poster_path", "backdrop_path"} else row[column] for column in columns]
            target.execute(
                f"INSERT INTO movies({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) "
                f"ON CONFLICT(id) DO UPDATE SET {assignments}",
                values,
            )
    media = _copy_missing_media(root / "catalog" / "posters", root / "data" / "posters")
    media += _copy_missing_media(root / "catalog" / "backdrops", root / "data" / "backdrops")
    return {"movies": len(rows), "media": media}
