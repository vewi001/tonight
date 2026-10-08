from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.database.db import db_session
from backend.movies.genres import canonical_genre


def profile_filters(db: Any, user_id: str) -> tuple[set[str], int, int]:
    excluded = {
        row["genre"]
        for row in db.execute("SELECT genre FROM taste_genre_exclusions WHERE user_id=?", (user_id,)).fetchall()
    }
    reset = db.execute(
        "SELECT swipe_rowid,feedback_rowid FROM taste_profile_resets WHERE user_id=?", (user_id,)
    ).fetchone()
    return excluded, int(reset["swipe_rowid"]) if reset else 0, int(reset["feedback_rowid"]) if reset else 0


def exclude_genre(user_id: str, genre: str) -> str:
    normalized = canonical_genre(genre)
    if not normalized:
        raise ValueError("Неизвестный жанр")
    with db_session() as db:
        db.execute(
            "INSERT OR IGNORE INTO taste_genre_exclusions(user_id,genre,created_at) VALUES(?,?,?)",
            (user_id, normalized, datetime.now().isoformat(timespec="seconds")),
        )
    return normalized


def reset_profile(user_id: str) -> None:
    """Start learning again while retaining the raw evening record."""
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        swipe_rowid = db.execute(
            "SELECT COALESCE(MAX(rowid),0) FROM swipes WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        feedback_rowid = db.execute(
            "SELECT COALESCE(MAX(rowid),0) FROM feedback WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        db.execute("DELETE FROM taste_genre_exclusions WHERE user_id=?", (user_id,))
        db.execute(
            """INSERT INTO taste_profile_resets(user_id,swipe_rowid,feedback_rowid,reset_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET swipe_rowid=excluded.swipe_rowid,
                feedback_rowid=excluded.feedback_rowid,reset_at=excluded.reset_at""",
            (user_id, swipe_rowid, feedback_rowid, now),
        )
