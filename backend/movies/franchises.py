from __future__ import annotations

from typing import Any

from backend.database.db import db_session
from backend.movies.catalog import is_released, row_to_movie


def _part_state(movie: dict[str, Any], parts: list[dict[str, Any]], watched: set[str]) -> bool:
    order = movie.get("franchise_order") or 1
    earlier = [part for part in parts if (part.get("franchise_order") or 0) < order]
    # If catalog metadata says this is part three but part two is absent, do
    # not pretend that the next step is known. The page remains informative.
    return len(earlier) >= order - 1 and all(part["id"] in watched for part in earlier)


def franchises() -> list[dict[str, Any]]:
    """Return local franchise progress without inferring views outside Tonight."""
    with db_session() as db:
        rows = db.execute(
            "SELECT * FROM movies WHERE franchise_key IS NOT NULL ORDER BY franchise_key,franchise_order,year,title"
        ).fetchall()
        watched = {row["movie_id"] for row in db.execute("SELECT movie_id FROM watch_history").fetchall()}
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["franchise_key"], []).append(row_to_movie(row))

    result: list[dict[str, Any]] = []
    for key, parts in groups.items():
        parts.sort(key=lambda movie: (movie.get("franchise_order") or 10_000, movie["year"], movie["title"]))
        display_parts = [
            {
                **movie,
                "watched": movie["id"] in watched,
                "released": is_released(movie),
                "available": is_released(movie) and _part_state(movie, parts, watched),
            }
            for movie in parts
        ]
        next_movie = next((movie for movie in display_parts if not movie["watched"] and movie["available"]), None)
        first = parts[0]
        result.append(
            {
                "key": key,
                "title": f"Серия «{first['title']}»",
                "parts": display_parts,
                "watched_count": sum(movie["watched"] for movie in display_parts),
                "next_movie": next_movie,
            }
        )
    return result
