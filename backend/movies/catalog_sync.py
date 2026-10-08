from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.config import settings
from backend.database.db import db_session, initialize


def sync_status() -> dict[str, Any]:
    # Also makes this safe for existing databases created before app_meta existed.
    initialize()
    with db_session() as db:
        row = db.execute("SELECT value FROM app_meta WHERE key='tmdb_catalog_sync_at'").fetchone()
        error = db.execute("SELECT value FROM app_meta WHERE key='tmdb_catalog_sync_error'").fetchone()
        trailer_row = db.execute("SELECT value FROM app_meta WHERE key='tmdb_trailer_sync_at'").fetchone()
    return {
        "enabled": bool(settings.tmdb_read_token and settings.catalog_auto_update),
        "last_sync_at": row["value"] if row else None,
        "last_error": error["value"] if error else None,
        "trailers_synced_at": trailer_row["value"] if trailer_row else None,
        "sources": ["trending_week", "popular", "top_rated"],
    }


def refresh_catalog_if_due() -> int:
    """Run the network sync only when explicitly configured, never during matching."""
    if not settings.tmdb_read_token or not settings.catalog_auto_update:
        return 0
    status = sync_status()
    last = status["last_sync_at"]
    with db_session() as db:
        missing_trailers = db.execute(
            "SELECT COUNT(*) FROM movies WHERE tmdb_id IS NOT NULL AND trailer_checked_at IS NULL"
        ).fetchone()[0]
    catalog_due = _needs_refresh(last)
    if not catalog_due and not missing_trailers:
        return 0
    try:
        from scripts.import_tmdb import backfill_trailers, import_smart_catalog

        imported = 0
        if catalog_due:
            imported = import_smart_catalog(
                settings.tmdb_read_token,
                pages=max(1, settings.catalog_pages),
                images=settings.catalog_images,
                min_votes=settings.catalog_min_votes,
            )
        checked = backfill_trailers(settings.tmdb_read_token)
    except Exception as exc:
        with db_session() as db:
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('tmdb_catalog_sync_error',?)", (type(exc).__name__,))
        return 0
    with db_session() as db:
        now = datetime.now().isoformat(timespec="seconds")
        if catalog_due:
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('tmdb_catalog_sync_at',?)", (now,))
        if checked:
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('tmdb_trailer_sync_at',?)", (now,))
        db.execute("DELETE FROM app_meta WHERE key='tmdb_catalog_sync_error'")
    return imported + checked


def _needs_refresh(last: str | None, now: datetime | None = None) -> bool:
    """A weekly feed refreshes when a new calendar week begins, not after 168 hours."""
    if not last:
        return True
    now = now or datetime.now()
    try:
        previous = datetime.fromisoformat(last)
    except ValueError:
        return True
    if settings.catalog_refresh_days >= 7:
        return previous.isocalendar()[:2] != now.isocalendar()[:2]
    return now - previous >= timedelta(days=max(1, settings.catalog_refresh_days))
