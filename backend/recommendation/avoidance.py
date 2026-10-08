from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.database.db import db_session, dumps, loads
from backend.movies.catalog import get_movie


def _rule(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "movie_id": row["movie_id"],
        "title": row["title"],
        "genres": loads(row["genres"], []),
        "keywords": loads(row["keywords"], []),
        "franchise_key": row["franchise_key"],
        "created_at": row["created_at"],
    }


def add_avoidance(user_id: str, movie_id: str) -> dict[str, Any]:
    movie = get_movie(movie_id)
    if not movie:
        raise ValueError("movie not found")
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.execute(
            """INSERT INTO avoid_similar(user_id,movie_id,genres,keywords,franchise_key,created_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,movie_id) DO UPDATE SET
            genres=excluded.genres,keywords=excluded.keywords,
            franchise_key=excluded.franchise_key,created_at=excluded.created_at""",
            (user_id, movie_id, dumps(movie["genres"]), dumps(movie["keywords"]), movie.get("franchise_key"), now),
        )
        row = db.execute(
            """SELECT a.*,m.title FROM avoid_similar a JOIN movies m ON m.id=a.movie_id
            WHERE a.user_id=? AND a.movie_id=?""",
            (user_id, movie_id),
        ).fetchone()
    return _rule(row)


def list_avoidances(user_id: str) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            """SELECT a.*,m.title FROM avoid_similar a JOIN movies m ON m.id=a.movie_id
            WHERE a.user_id=? ORDER BY a.created_at DESC,a.id DESC""",
            (user_id,),
        ).fetchall()
    return [_rule(row) for row in rows]


def remove_avoidance(rule_id: int, user_id: str) -> None:
    with db_session() as db:
        deleted = db.execute("DELETE FROM avoid_similar WHERE id=? AND user_id=?", (rule_id, user_id)).rowcount
    if not deleted:
        raise ValueError("avoidance not found")


def load_avoidance_rules(db: Any, user_id: str) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM avoid_similar WHERE user_id=?", (user_id,)).fetchall()
    return [
        {
            "movie_id": row["movie_id"],
            "genres": loads(row["genres"], []),
            "keywords": loads(row["keywords"], []),
            "franchise_key": row["franchise_key"],
        }
        for row in rows
    ]


def similarity_penalty(movie: dict[str, Any], rules: list[dict[str, Any]]) -> float:
    """Strongly lower close matches without ever turning a trait into a filter."""
    candidate_genres = set(movie.get("genres") or [])
    candidate_keywords = {str(item).casefold() for item in movie.get("keywords") or []}
    strongest = 0.0
    for rule in rules:
        genre_overlap = candidate_genres.intersection(rule.get("genres") or [])
        keyword_overlap = candidate_keywords.intersection(
            str(item).casefold() for item in rule.get("keywords") or []
        )
        penalty = min(0.12, 0.04 * len(genre_overlap)) + min(0.15, 0.05 * len(keyword_overlap))
        if movie.get("id") == rule.get("movie_id"):
            penalty += 0.10
        if movie.get("franchise_key") and movie.get("franchise_key") == rule.get("franchise_key"):
            penalty = max(penalty, 0.34)
        strongest = max(strongest, min(0.40, penalty))
    return strongest
