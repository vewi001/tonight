from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.database.db import db_session, loads
from backend.movies.genres import canonical_genre


def taste_signals(db: Any, user_id: str, session_id: int | None = None) -> list[dict[str, Any]]:
    """Read the existing IQ evidence and respect corrections/reset cutoffs.

    A later reaction replaces an earlier one for the same film; a viewing rating
    takes precedence. No second persisted preference profile is maintained.
    """
    excluded, swipe_cutoff, feedback_cutoff = profile_filters(db, user_id)
    query = "SELECT s.movie_id,s.reaction,m.* FROM swipes s JOIN movies m ON m.id=s.movie_id WHERE s.user_id=? AND s.rowid>?"
    args: list[Any] = [user_id, swipe_cutoff]
    if session_id is not None:
        query += " AND s.session_id=?"
        args.append(session_id)
    query += " ORDER BY s.created_at,s.rowid"
    evidence = {}
    values = {"love": 1.0, "like": .6, "okay": 0., "dislike": -1.}
    for row in db.execute(query, args):
        if row['reaction'] in values:
            evidence[row['movie_id']] = (dict(row), values[row['reaction']])
    # Discovery interest is deliberately weaker than a rating; later marks win.
    reset = db.execute('SELECT reset_at FROM taste_profile_resets WHERE user_id=?', (user_id,)).fetchone()
    for row in db.execute("SELECT a.movie_id,a.action,m.* FROM viewer_movie_actions a JOIN movies m ON m.id=a.movie_id WHERE a.user_id=? AND a.action IN ('dislike','interest') AND a.created_at>? ORDER BY a.created_at,a.rowid", (user_id, reset['reset_at'] if reset else '')):
        evidence[row['movie_id']] = (dict(row), -1. if row['action'] == 'dislike' else .3)
    for row in db.execute(
        """SELECT h.movie_id,f.rating,m.* FROM feedback f JOIN watch_history h ON h.id=f.history_id
        JOIN movies m ON m.id=h.movie_id WHERE f.user_id=? AND f.rowid>?
        ORDER BY f.created_at,f.rowid""", (user_id, feedback_cutoff)
    ):
        evidence[row['movie_id']] = (dict(row), (row['rating'] - 3) / 2)
    from backend.movies.genres import normalize_genres
    return [{**movie, 'value': value,
             'genres': [g for g in normalize_genres(loads(movie['genres'], [])) if g not in excluded],
             'keywords': loads(movie['keywords'], []), 'cast_names': loads(movie['cast_names'], [])}
            for movie, value in evidence.values()]


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
    now = datetime.now().isoformat()
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
