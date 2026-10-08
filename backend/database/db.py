from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from backend.config import settings


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or settings.db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def db_session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db = connect(path)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def generate_access_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS movies (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER NOT NULL,
    release_date TEXT,
    genres TEXT NOT NULL,
    overview TEXT,
    runtime INTEGER,
    rating REAL,
    vote_count INTEGER DEFAULT 0,
    keywords TEXT DEFAULT '[]',
    director TEXT,
    cast_names TEXT DEFAULT '[]',
    poster_path TEXT,
    backdrop_path TEXT,
    franchise_key TEXT,
    franchise_order INTEGER,
    tmdb_id INTEGER,
    trailer_key TEXT,
    trailer_language TEXT,
    trailer_checked_at TEXT,
    catalog_sources TEXT DEFAULT '[]',
    source TEXT DEFAULT 'starter'
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'choosing',
    selected_movie_id TEXT,
    recommendations TEXT DEFAULT '[]',
    rejected_movies TEXT DEFAULT '[]',
    access_code TEXT NOT NULL DEFAULT '000000',
    selected_at TEXT,
    reconnect_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(selected_movie_id) REFERENCES movies(id)
);
CREATE TABLE IF NOT EXISTS participants (
    session_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    moods TEXT DEFAULT '[]',
    energy TEXT,
    max_runtime INTEGER,
    min_year INTEGER,
    disliked_genres TEXT DEFAULT '[]',
    progress INTEGER NOT NULL DEFAULT 0,
    ready INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT NOT NULL,
    PRIMARY KEY(session_id, user_id),
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS swipes (
    session_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    movie_id TEXT NOT NULL,
    reaction TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(session_id, user_id, movie_id),
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(movie_id) REFERENCES movies(id)
);
CREATE TABLE IF NOT EXISTS swipe_decks (
    session_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    movie_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY(session_id, user_id, movie_id),
    UNIQUE(session_id, user_id, position),
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(movie_id) REFERENCES movies(id)
);
CREATE TABLE IF NOT EXISTS watch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER UNIQUE,
    movie_id TEXT NOT NULL,
    watched_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(movie_id) REFERENCES movies(id)
);
CREATE TABLE IF NOT EXISTS feedback (
    history_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL,
    PRIMARY KEY(history_id, user_id),
    FOREIGN KEY(history_id) REFERENCES watch_history(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS evening_feedback (
    history_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    fit INTEGER NOT NULL CHECK(fit IN (0,1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(history_id, user_id),
    FOREIGN KEY(history_id) REFERENCES watch_history(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS watchlist (
    movie_id TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL,
    saved_by TEXT,
    deferred_reason TEXT,
    FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS weekly_picks (
    week_start TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 5),
    movie_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    PRIMARY KEY(week_start, position),
    UNIQUE(week_start, movie_id),
    FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS avoid_similar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    movie_id TEXT NOT NULL,
    genres TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    franchise_key TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, movie_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS taste_genre_exclusions (
    user_id TEXT NOT NULL,
    genre TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id, genre),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS taste_profile_resets (
    user_id TEXT PRIMARY KEY,
    swipe_rowid INTEGER NOT NULL DEFAULT 0,
    feedback_rowid INTEGER NOT NULL DEFAULT 0,
    reset_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(session_date);
CREATE INDEX IF NOT EXISTS idx_swipes_session ON swipes(session_id, user_id);
CREATE INDEX IF NOT EXISTS idx_swipe_decks_session ON swipe_decks(session_id, user_id, position);
CREATE INDEX IF NOT EXISTS idx_history_movie ON watch_history(movie_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_saved_at ON watchlist(saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_weekly_picks_week ON weekly_picks(week_start, position);
CREATE INDEX IF NOT EXISTS idx_avoid_similar_user ON avoid_similar(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_taste_genre_exclusions_user ON taste_genre_exclusions(user_id);
"""


def initialize(path: Path | None = None) -> None:
    with db_session(path) as db:
        db.executescript(SCHEMA)
        # Existing installations predate franchise metadata. SQLite's CREATE
        # TABLE cannot add columns to them, so make this migration idempotent.
        movie_columns = {row["name"] for row in db.execute("PRAGMA table_info(movies)").fetchall()}
        if "franchise_key" not in movie_columns:
            db.execute("ALTER TABLE movies ADD COLUMN franchise_key TEXT")
        if "franchise_order" not in movie_columns:
            db.execute("ALTER TABLE movies ADD COLUMN franchise_order INTEGER")
        session_columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)").fetchall()}
        if "access_code" not in session_columns:
            db.execute("ALTER TABLE sessions ADD COLUMN access_code TEXT")
        if "selected_at" not in session_columns:
            db.execute("ALTER TABLE sessions ADD COLUMN selected_at TEXT")
        if "reconnect_count" not in session_columns:
            db.execute("ALTER TABLE sessions ADD COLUMN reconnect_count INTEGER NOT NULL DEFAULT 0")
        missing_codes = db.execute("SELECT id FROM sessions WHERE access_code IS NULL OR length(access_code) != 6").fetchall()
        for row in missing_codes:
            db.execute("UPDATE sessions SET access_code=? WHERE id=?", (generate_access_code(), row["id"]))
        migrations = {
            "release_date": "TEXT",
            "tmdb_id": "INTEGER",
            "trailer_key": "TEXT",
            "trailer_language": "TEXT",
            "trailer_checked_at": "TEXT",
            "catalog_sources": "TEXT DEFAULT '[]'",
        }
        for column, definition in migrations.items():
            if column not in movie_columns:
                db.execute(f"ALTER TABLE movies ADD COLUMN {column} {definition}")
        watchlist_columns = {row["name"] for row in db.execute("PRAGMA table_info(watchlist)").fetchall()}
        if "saved_by" not in watchlist_columns:
            db.execute("ALTER TABLE watchlist ADD COLUMN saved_by TEXT")
        if "deferred_reason" not in watchlist_columns:
            db.execute("ALTER TABLE watchlist ADD COLUMN deferred_reason TEXT")
        db.execute(
            """UPDATE movies SET tmdb_id=CAST(substr(id,6) AS INTEGER)
            WHERE tmdb_id IS NULL AND id GLOB 'tmdb-[0-9]*'"""
        )
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_movies_tmdb_id ON movies(tmdb_id) WHERE tmdb_id IS NOT NULL")
        now = datetime.now().isoformat(timespec="seconds")
        profiles = [
            ("lera", "Первый зритель", "🍿", "Лера"),
            ("nikita", "Второй зритель", "🎬", "Никита"),
        ]
        db.executemany(
            "INSERT OR IGNORE INTO users(id,name,emoji,created_at) VALUES(?,?,?,?)",
            [(user_id, name, emoji, now) for user_id, name, emoji, _ in profiles],
        )
        # Keep the stable IDs referenced by history and ratings, but replace the
        # old product-specific labels. A future custom label is left untouched.
        for user_id, name, emoji, legacy_name in profiles:
            db.execute(
                "UPDATE users SET name=?,emoji=? WHERE id=? AND name IN (?,?)",
                (name, emoji, user_id, legacy_name, name),
            )
