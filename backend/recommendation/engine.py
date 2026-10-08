from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.config import SCORING
from backend.database.db import db_session, loads
from backend.movies.catalog import _franchise_is_available, is_released, row_to_movie
from backend.movies.genres import normalize_genres
from backend.recommendation.avoidance import load_avoidance_rules, similarity_penalty
from backend.recommendation.taste_profile import profile_filters

REACTION_SCORE = {"love": 0.98, "like": 0.80, "okay": 0.60, "dislike": 0.04, "unseen": 0.52}
MOOD_GENRES = {
    "laugh": {"комедия"}, "smart": {"драма", "sci-fi", "детектив"},
    "scary": {"хоррор", "триллер"}, "emotional": {"драма", "романтика"},
    "cozy": {"комедия", "семейный", "мультфильм", "приключения"},
    "action": {"боевик", "приключения"}, "mystery": {"детектив", "триллер", "загадка"},
    "wow": {"sci-fi", "триллер", "загадка"}, "romance": {"романтика"},
    "atmosphere": {"драма", "sci-fi", "фэнтези"}, "surprise": set(),
}


def compatibility_score(person_a: float, person_b: float, pair_history: float = 0.5, catalog: float = 0.5) -> float:
    """Fair joint score: the least-happy viewer matters more than the average."""
    a, b = max(0.0, min(1.0, person_a)), max(0.0, min(1.0, person_b))
    average = (a + b) / 2
    minimum = min(a, b)
    disagreement = abs(a - b)
    strong_dislike = max(0.0, 0.35 - minimum) / 0.35
    raw = (
        SCORING["average_weight"] * average
        + SCORING["minimum_weight"] * minimum
        + SCORING["pair_history_weight"] * pair_history
        + SCORING["catalog_weight"] * catalog
        - SCORING["disagreement_penalty"] * disagreement
        - SCORING["strong_dislike_penalty"] * strong_dislike
    )
    return max(0.0, min(1.0, raw))


def _participant_context(db: Any, session_id: int, user_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM participants WHERE session_id=? AND user_id=?", (session_id, user_id)).fetchone()
    if not row:
        return {"moods": [], "energy": "medium", "disliked": [], "max_runtime": None, "min_year": None}
    return {
        "moods": loads(row["moods"], []), "energy": row["energy"] or "medium",
        "disliked": normalize_genres(loads(row["disliked_genres"], [])), "max_runtime": row["max_runtime"], "min_year": row["min_year"],
    }


def _taste_profile(db: Any, session_id: int, user_id: str) -> tuple[dict[str, float], dict[str, float]]:
    genre_points: dict[str, list[float]] = defaultdict(list)
    keyword_points: dict[str, list[float]] = defaultdict(list)
    excluded_genres, swipe_cutoff, feedback_cutoff = profile_filters(db, user_id)
    rows = db.execute(
        """SELECT s.rowid signal_rowid,m.genres,m.keywords,s.reaction FROM swipes s JOIN movies m ON m.id=s.movie_id
        WHERE s.session_id=? AND s.user_id=? AND s.rowid>?""", (session_id, user_id, swipe_cutoff)
    ).fetchall()
    for row in rows:
        value = REACTION_SCORE[row["reaction"]]
        if row["reaction"] == "unseen":
            continue
        for genre in normalize_genres(loads(row["genres"], [])):
            if genre not in excluded_genres: genre_points[genre].append(value)
        for keyword in loads(row["keywords"], []): keyword_points[keyword].append(value)
    history = db.execute(
        """SELECT f.rowid signal_rowid,m.genres,m.keywords,f.rating FROM feedback f
        JOIN watch_history h ON h.id=f.history_id JOIN movies m ON m.id=h.movie_id
        WHERE f.user_id=? AND f.rowid>?""", (user_id, feedback_cutoff)
    ).fetchall()
    for row in history:
        value = (row["rating"] - 1) / 4
        for genre in normalize_genres(loads(row["genres"], [])):
            if genre not in excluded_genres: genre_points[genre].append(value)
        for keyword in loads(row["keywords"], []): keyword_points[keyword].append(value)
    return (
        {key: sum(values) / len(values) for key, values in genre_points.items()},
        {key: sum(values) / len(values) for key, values in keyword_points.items()},
    )


def _pair_profile(db: Any) -> dict[str, float]:
    points: dict[str, list[float]] = defaultdict(list)
    rows = db.execute(
        """SELECT m.genres, AVG(f.rating) pair_rating, COUNT(f.rating) rating_count,
        (SELECT AVG(fit) FROM evening_feedback WHERE history_id=h.id) evening_fit,
        (SELECT COUNT(*) FROM evening_feedback WHERE history_id=h.id) evening_count
        FROM watch_history h JOIN movies m ON m.id=h.movie_id JOIN feedback f ON f.history_id=h.id
        GROUP BY h.id HAVING rating_count=2"""
    ).fetchall()
    for row in rows:
        movie_value = (float(row["pair_rating"]) - 1) / 4
        value = (0.35 * movie_value + 0.65 * float(row["evening_fit"])) if row["evening_count"] == 2 else movie_value
        for genre in normalize_genres(loads(row["genres"], [])): points[genre].append(value)
    return {key: sum(values) / len(values) for key, values in points.items()}


def _person_score(movie: dict[str, Any], prefs: dict[str, Any], genres: dict[str, float], keywords: dict[str, float], direct: str | None) -> float:
    if direct and direct != "unseen":
        base = REACTION_SCORE[direct]
    else:
        rating = movie.get("rating")
        catalog = max(0.0, min(1.0, (float(rating) - 4.5) / 4.5)) if rating is not None else 0.42
        genre_values = [genres[g] for g in movie["genres"] if g in genres]
        keyword_values = [keywords[k] for k in movie["keywords"] if k in keywords]
        learned = (sum(genre_values) / len(genre_values)) if genre_values else 0.58
        detail = (sum(keyword_values) / len(keyword_values)) if keyword_values else learned
        base = 0.32 * catalog + 0.48 * learned + 0.20 * detail

    desired = set().union(*(MOOD_GENRES.get(mood, set()) for mood in prefs["moods"]))
    if desired and desired.intersection(movie["genres"]):
        base += SCORING["vibe_match"]
    energy = prefs.get("energy")
    if energy == "low" and ((movie["runtime"] or 0) > 130 or "драма" in movie["genres"] and movie["rating"] < 7.4):
        base -= SCORING["energy_mismatch"]
    if energy == "high" and ({"загадка", "sci-fi", "триллер"} & set(movie["genres"])):
        base += 0.04
    return max(0.0, min(1.0, base))


def _explanation(name: str, score: float, movie: dict[str, Any], prefs: dict[str, Any]) -> str:
    desired = set().union(*(MOOD_GENRES.get(mood, set()) for mood in prefs["moods"]))
    matches = [genre for genre in movie["genres"] if genre in desired]
    if matches:
        return f"Попадает в сегодняшний вайб: {', '.join(matches[:2])}. И по вкусу {name} выглядит уверенно."
    if score >= 0.76:
        return f"Хорошо совпадает с реакциями {name} и не спорит с сегодняшними ограничениями."
    return f"Мягкий компромисс: знакомый жанровый рисунок без явных стоп-сигналов для {name}."


def _plain_reasons(
    movie: dict[str, Any],
    people: dict[str, dict[str, Any]],
    direct: dict[tuple[str, str], str],
    person_scores: dict[str, float],
    effective_max_runtime: int | None,
) -> list[str]:
    """Return two short, user-facing facts without exposing ranking internals."""
    reasons: list[str] = []
    positive = {
        user for user in ("lera", "nikita")
        if direct.get((user, movie["id"])) in {"love", "like"}
    }
    if positive == {"lera", "nikita"}:
        reasons.append("Этот фильм понравился вам обоим на быстрых карточках.")
    elif positive:
        name = "первому зрителю" if "lera" in positive else "второму зрителю"
        reasons.append(f"На быстрых карточках он понравился {name}.")

    desired = set().union(*(
        MOOD_GENRES.get(mood, set())
        for person in people.values()
        for mood in person["moods"]
    ))
    matching_genres = [genre for genre in movie["genres"] if genre in desired]
    if matching_genres:
        reasons.append(f"Подходит под выбранное настроение: {', '.join(matching_genres[:2])}.")
    if effective_max_runtime and movie.get("runtime"):
        reasons.append(f"Укладывается в выбранное время — {movie['runtime']} минут.")
    if movie.get("rating") and float(movie["rating"]) >= 7:
        reasons.append(f"Зрители оценивают его высоко — {float(movie['rating']):.1f} из 10.")
    if abs(person_scores["lera"] - person_scores["nikita"]) <= 0.15:
        reasons.append("Он одинаково хорошо подходит вам обоим.")

    fallbacks = [
        "При выборе учтены сегодняшние реакции обоих зрителей.",
        "Фильм подходит под выбранные вами рамки вечера.",
    ]
    for reason in fallbacks:
        if len(reasons) >= 2:
            break
        reasons.append(reason)
    return reasons[:2]


def recommend(session_id: int, limit: int = 7) -> list[dict[str, Any]]:
    with db_session() as db:
        people = {user: _participant_context(db, session_id, user) for user in ("lera", "nikita")}
        taste = {user: _taste_profile(db, session_id, user) for user in ("lera", "nikita")}
        pair = _pair_profile(db)
        session = db.execute("SELECT rejected_movies FROM sessions WHERE id=?", (session_id,)).fetchone()
        rejected = set(loads(session["rejected_movies"], [])) if session else set()
        watched = {row[0] for row in db.execute("SELECT movie_id FROM watch_history").fetchall()}
        rows = db.execute("SELECT * FROM movies").fetchall()
        direct_rows = db.execute("SELECT user_id,movie_id,reaction FROM swipes WHERE session_id=?", (session_id,)).fetchall()
        direct = {(row["user_id"], row["movie_id"]): row["reaction"] for row in direct_rows}
        avoidance = {user: load_avoidance_rules(db, user) for user in ("lera", "nikita")}

    disliked = set(people["lera"]["disliked"]) | set(people["nikita"]["disliked"])
    catalog = [row_to_movie(row) for row in rows]
    runtimes = [p["max_runtime"] for p in people.values() if p["max_runtime"]]
    years = [p["min_year"] for p in people.values() if p["min_year"]]
    max_runtime = min(runtimes) if runtimes else None
    min_year = max(years) if years else None
    # Genre exclusions are promises, not preferences: never relax them.  A small
    # local catalog can however make a year/runtime intersection empty, so widen
    # those two non-genre constraints progressively rather than strand the pair
    # on an error screen.
    base_candidates: list[dict[str, Any]] = []
    for movie in catalog:
        if movie["id"] in rejected or movie["id"] in watched:
            continue
        if not is_released(movie):
            continue
        if movie["rating"] is None or movie["rating"] <= 0 or (movie.get("vote_count") or 0) < 5:
            continue
        if not _franchise_is_available(movie, watched, catalog):
            continue
        if disliked.intersection(movie["genres"]):
            continue
        base_candidates.append(movie)

    effective_max_runtime, effective_min_year = max_runtime, min_year
    relaxed_constraints: list[str] = []
    candidates = base_candidates
    while base_candidates:
        candidates = [
            movie for movie in base_candidates
            if (not effective_max_runtime or not movie["runtime"] or movie["runtime"] <= effective_max_runtime)
            and (not effective_min_year or movie["year"] >= effective_min_year)
        ]
        if candidates:
            break
        if effective_max_runtime is not None:
            effective_max_runtime = None
            relaxed_constraints.append("длительность")
            continue
        if effective_min_year is not None:
            effective_min_year = None
            relaxed_constraints.append("эпоха")
            continue
        break

    output: list[dict[str, Any]] = []
    for movie in candidates:
        person_scores = {}
        for user in ("lera", "nikita"):
            genres, keywords = taste[user]
            person_scores[user] = _person_score(movie, people[user], genres, keywords, direct.get((user, movie["id"])))
            person_scores[user] = max(0.0, person_scores[user] - similarity_penalty(movie, avoidance[user]))
        pair_values = [pair[g] for g in movie["genres"] if g in pair]
        pair_score = sum(pair_values) / len(pair_values) if pair_values else 0.56
        catalog_score = max(0.0, min(1.0, (float(movie["rating"]) - 4.5) / 4.5))
        joint = compatibility_score(person_scores["lera"], person_scores["nikita"], pair_score, catalog_score)
        # UI score, deliberately calibrated as a compatibility index rather than
        # an inflated probability. 0.70 internal confidence becomes ~82%, not 95%.
        percent = max(45, min(98, round(45 + 53 * joint)))
        movie.update({
            "score": round(joint, 5), "match": percent,
            "person_scores": {key: round(value, 4) for key, value in person_scores.items()},
            "plain_reasons": _plain_reasons(movie, people, direct, person_scores, effective_max_runtime),
            "stop_genres_respected": not bool(disliked.intersection(movie["genres"])),
            "explanation_lera": _explanation("первого зрителя", person_scores["lera"], movie, people["lera"]),
            "explanation_nikita": _explanation("второго зрителя", person_scores["nikita"], movie, people["nikita"]),
            "compromise": "Оба прогноза держатся близко друг к другу — никто не приносит свой вечер в жертву чужому выбору.",
            "relaxed_constraints": relaxed_constraints,
            "applied_max_runtime": effective_max_runtime,
            "applied_min_year": effective_min_year,
        })
        output.append(movie)
    output.sort(key=lambda item: item["score"], reverse=True)
    return output[:limit]
