from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any

from backend.database.db import db_session
from backend.movies.catalog import _franchise_is_available, is_released, row_to_movie
from backend.recommendation.engine import _pair_profile


def _week_start(reference_day: date) -> date:
    return reference_day - timedelta(days=reference_day.weekday())


def _reason(movie: dict[str, Any], pair_profile: dict[str, float]) -> str:
    familiar = [genre for genre in movie["genres"] if pair_profile.get(genre, 0.0) >= 0.65]
    if familiar:
        return f"Вам уже нравились вместе фильмы с жанром «{familiar[0]}»."
    return "Свежий вариант на общий вечер — решите в день просмотра."


def _score(movie: dict[str, Any], pair_profile: dict[str, float], week: date) -> tuple[float, str]:
    genre_values = [pair_profile[genre] for genre in movie["genres"] if genre in pair_profile]
    taste = sum(genre_values) / len(genre_values) if genre_values else 0.55
    rating = max(0.0, min(1.0, ((movie.get("rating") or 5.0) - 5.0) / 4.5))
    tie_breaker = sha256(f"{week.isoformat()}:{movie['id']}".encode()).hexdigest()
    return 0.68 * taste + 0.32 * rating, tie_breaker


def _stored_picks(db: Any, week: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT m.*,p.reason FROM weekly_picks p JOIN movies m ON m.id=p.movie_id
        WHERE p.week_start=? ORDER BY p.position""",
        (week,),
    ).fetchall()
    return [{**row_to_movie(row), "weekly_reason": row["reason"]} for row in rows]


def weekly_picks(reference_day: date | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """Build one stable, entirely local five-film shortlist for each week."""
    if limit != 5:
        raise ValueError("weekly shortlist always contains five movies")
    week = _week_start(reference_day or date.today())
    week_key = week.isoformat()
    with db_session() as db:
        stored = _stored_picks(db, week_key)
        existing = [movie for movie in stored if is_released(movie, week)]
        if len(existing) == limit:
            return existing
        if stored:
            db.execute("DELETE FROM weekly_picks WHERE week_start=?", (week_key,))

        watched = {row["movie_id"] for row in db.execute("SELECT movie_id FROM watch_history").fetchall()}
        saved = {row["movie_id"] for row in db.execute("SELECT movie_id FROM watchlist").fetchall()}
        catalog = [row_to_movie(row) for row in db.execute("SELECT * FROM movies").fetchall()]
        candidates = [
            movie for movie in catalog
            if movie["id"] not in watched
            and movie["id"] not in saved
            and is_released(movie, week)
            and (movie.get("rating") or 0) > 0
            and _franchise_is_available(movie, watched, catalog)
        ]
        pair_profile = _pair_profile(db)
        ranked = sorted(candidates, key=lambda movie: (-_score(movie, pair_profile, week)[0], _score(movie, pair_profile, week)[1]))

        chosen: list[dict[str, Any]] = []
        covered_genres: set[str] = set()
        for movie in ranked:
            if not covered_genres.intersection(movie["genres"]):
                chosen.append(movie)
                covered_genres.update(movie["genres"])
            if len(chosen) == limit:
                break
        for movie in ranked:
            if movie not in chosen:
                chosen.append(movie)
            if len(chosen) == limit:
                break

        now = datetime.now().isoformat(timespec="seconds")
        for position, movie in enumerate(chosen, start=1):
            db.execute(
                "INSERT INTO weekly_picks(week_start,position,movie_id,reason,generated_at) VALUES(?,?,?,?,?)",
                (week_key, position, movie["id"], _reason(movie, pair_profile), now),
            )
        return _stored_picks(db, week_key)
