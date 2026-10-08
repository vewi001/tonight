from __future__ import annotations

import random
from datetime import date
from pathlib import Path
from typing import Any

from backend.database.db import db_session, loads
from backend.movies.genres import normalize_genres
from backend.movies.media import local_media
from backend.movies.trailers import trailer_url


def media_url(movie_id: str, kind: str, stored_path: str | None = None) -> str:
    """Return a cache-busted URL that changes when a real local image appears."""
    cached = Path(stored_path) if stored_path else local_media(movie_id, kind)
    version = str(cached.stat().st_mtime_ns) if cached and cached.exists() else "fallback-2"
    return f"/api/movies/{movie_id}/{kind}?v={version}"


def row_to_movie(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "title": row["title"], "original_title": row["original_title"],
        "year": row["year"], "release_date": row["release_date"], "genres": normalize_genres(loads(row["genres"], [])), "overview": row["overview"] or "",
        "runtime": row["runtime"], "rating": row["rating"], "vote_count": row["vote_count"],
        "keywords": loads(row["keywords"], []), "director": row["director"],
        "franchise_key": row["franchise_key"], "franchise_order": row["franchise_order"],
        "tmdb_id": row["tmdb_id"], "trailer_url": trailer_url(row["trailer_key"]),
        "poster_url": media_url(row["id"], "poster", row["poster_path"]),
        "backdrop_url": media_url(row["id"], "backdrop", row["backdrop_path"]),
    }


def is_released(movie: dict[str, Any], reference_day: date | None = None) -> bool:
    """Only offer films whose official release has already happened.

    Older catalog records did not save a full release date. They are safe when
    their year has already passed; current-year records without an exact date
    stay hidden until a catalog refresh can verify them.
    """
    reference_day = reference_day or date.today()
    release = movie.get("release_date")
    if release:
        try:
            return date.fromisoformat(str(release)) <= reference_day
        except ValueError:
            return False
    year = movie.get("year")
    return isinstance(year, int) and year < reference_day.year


def get_movie(movie_id: str) -> dict[str, Any] | None:
    with db_session() as db:
        row = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
    return row_to_movie(row) if row else None


def all_movies() -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute("SELECT * FROM movies ORDER BY rating DESC, title").fetchall()
    return [row_to_movie(row) for row in rows]


def search_movies(query: str, limit: int = 12) -> list[dict[str, Any]]:
    terms = [term for term in query.lower().replace("ё", "е").split() if len(term) > 1 and term not in {"как", "что", "мне", "хочу", "фильм"}]
    if not terms:
        return []
    results: list[tuple[int, dict[str, Any]]] = []
    for movie in all_movies():
        if not is_released(movie):
            continue
        haystacks = {"title": f"{movie['title']} {movie.get('original_title') or ''}".lower(), "keywords": " ".join(movie.get("keywords") or []).lower(), "genres": " ".join(movie.get("genres") or []).lower(), "overview": (movie.get("overview") or "").lower()}
        score = sum(8 if term in haystacks["title"] else 4 if term in haystacks["keywords"] else 2 if term in haystacks["genres"] else 1 if term in haystacks["overview"] else 0 for term in terms)
        if score: results.append((score, movie))
    return [movie for _, movie in sorted(results, key=lambda item: (-item[0], -(item[1].get("rating") or 0), item[1]["title"]))[:limit]]


def swipe_deck(
    session_id: int,
    user_id: str,
    count: int = 12,
    excluded_genres: set[str] | None = None,
) -> list[dict[str, Any]]:
    movies = all_movies()
    # A title with no audience score is usually an unreleased TMDB placeholder,
    # not a useful option for a film night. Do not put it into reaction decks.
    movies = [movie for movie in movies if is_released(movie) and movie["rating"] is not None and movie["rating"] > 0 and (movie["vote_count"] or 0) >= 5]
    # A sequel is never a discovery card until the couple has watched every
    # earlier known entry in its franchise. This avoids accidentally starting
    # from part two during the quick-reaction phase as well as in the finale.
    with db_session() as db:
        watched = {row[0] for row in db.execute("SELECT movie_id FROM watch_history").fetchall()}
    movies = [movie for movie in movies if _franchise_is_available(movie, watched, movies)]
    excluded = set(normalize_genres(list(excluded_genres or set())))
    if excluded:
        movies = [movie for movie in movies if not excluded.intersection(movie["genres"])]
    rng = random.Random(f"tonight:{session_id}:{user_id}")
    rng.shuffle(movies)
    chosen: list[dict[str, Any]] = []
    covered: set[str] = set()
    for movie in movies:
        new_genres = set(movie["genres"]) - covered
        # Keep the opening cards varied, then reliably fill the requested
        # length. Using count//2 here made a 20+ card deck wait for more unique
        # genres than the catalog contains and silently stop around 8–13.
        if new_genres or len(chosen) >= min(8, count // 2):
            chosen.append(movie)
            covered.update(movie["genres"])
        if len(chosen) == count:
            break
    return chosen


def _franchise_is_available(movie: dict[str, Any], watched: set[str], catalog: list[dict[str, Any]]) -> bool:
    order = movie.get("franchise_order")
    key = movie.get("franchise_key")
    if not key or not order or order <= 1:
        return True
    earlier = [item for item in catalog if item.get("franchise_key") == key and (item.get("franchise_order") or 0) < order]
    # If metadata declares this a sequel but an earlier part is outside the
    # current local catalog, keep it hidden too: we cannot prove it was seen.
    return len(earlier) >= order - 1 and all(item["id"] in watched for item in earlier)
