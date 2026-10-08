"""Deletion of user-owned Tonight data while preserving the local catalog."""
from __future__ import annotations

from pathlib import Path

from backend.database.db import connect, db_session


PERSONAL_TABLES = (
    "feedback",
    "evening_feedback",
    "watch_history",
    "swipe_decks",
    "swipes",
    "participants",
    "sessions",
    "watchlist",
    "weekly_picks",
    "avoid_similar",
    "taste_genre_exclusions",
    "taste_profile_resets",
)


class PrivacyDeleteError(RuntimeError):
    """A safe precondition prevented complete deletion."""


def _delete_local_backups(backup_dir: Path) -> int:
    if not backup_dir.exists():
        return 0
    candidates = [path for path in backup_dir.iterdir() if path.is_file() or path.is_symlink()]
    deleted = 0
    for path in candidates:
        try:
            path.unlink()
        except OSError as exc:
            raise PrivacyDeleteError(
                "Не получилось удалить локальную резервную копию. Закройте программы, которые могли её открыть, и попробуйте снова."
            ) from exc
        deleted += 1
    return deleted


def delete_personal_data(database: Path, backup_dir: Path) -> dict[str, int]:
    """Irreversibly clear personal rows and Tonight-managed local backups."""
    # Refuse to clear the main database when a managed backup cannot be removed:
    # otherwise the UI could claim full deletion while a recoverable copy remains.
    backups_deleted = _delete_local_backups(backup_dir)
    with db_session(database) as db:
        db.execute("PRAGMA secure_delete=ON")
        deleted_rows = sum(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in PERSONAL_TABLES)
        for table in PERSONAL_TABLES:
            db.execute(f'DELETE FROM "{table}"')
        db.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ('sessions','watch_history','avoid_similar')"
        )

    # VACUUM rewrites the database without freed pages; the checkpoint removes
    # deleted content that could otherwise remain in the WAL file.
    db = connect(database)
    try:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("VACUUM")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close()

    return {"deleted_rows": deleted_rows, "backups_deleted": backups_deleted}
