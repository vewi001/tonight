from __future__ import annotations

import random
from datetime import date, datetime
from typing import Any

from backend.config import settings
from backend.database.db import connect, db_session, dumps, generate_access_code, loads
from backend.movies.catalog import get_movie, is_released, row_to_movie, swipe_deck
from backend.movies.genres import normalize_genres
from backend.recommendation.engine import MOOD_GENRES

RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
RU_WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def _title(day: date) -> str:
    return f"{RU_WEEKDAYS[day.weekday()]}, {day.day} {RU_MONTHS[day.month - 1]}"


def active_session(create: bool = True) -> dict[str, Any] | None:
    today = date.today().isoformat()
    with db_session() as db:
        row = db.execute("SELECT * FROM sessions WHERE session_date=? ORDER BY id DESC LIMIT 1", (today,)).fetchone()
        if not row and create:
            now = datetime.now().isoformat(timespec="seconds")
            cur = db.execute(
                "INSERT INTO sessions(session_date,title,status,access_code,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (today, _title(date.today()), "choosing", generate_access_code(), now, now),
            )
            row = db.execute("SELECT * FROM sessions WHERE id=?", (cur.lastrowid,)).fetchone()
        return session_state(row["id"], db) if row else None


def session_access_code(session_id: int) -> str:
    with db_session() as db:
        row = db.execute("SELECT access_code FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("session not found")
        return row["access_code"]


def ensure_participant(session_id: int, user_id: str) -> None:
    with db_session() as db:
        db.execute(
            "INSERT OR IGNORE INTO participants(session_id,user_id,joined_at) VALUES(?,?,?)",
            (session_id, user_id, datetime.now().isoformat(timespec="seconds")),
        )


def save_preferences(session_id: int, payload: Any) -> None:
    ensure_participant(session_id, payload.user_id)
    with db_session() as db:
        db.execute(
            """UPDATE participants SET moods=?,energy=?,max_runtime=?,min_year=?,disliked_genres=?
            WHERE session_id=? AND user_id=?""",
            (dumps(payload.moods), payload.energy, payload.max_runtime, payload.min_year, dumps(payload.disliked_genres), session_id, payload.user_id),
        )


def _deck_for_user(session_id: int, user_id: str) -> list[dict[str, Any]]:
    # The deck is a snapshot, not a live query. Otherwise a background catalog
    # refresh (or a newly watched prequel) can replace a card already visible in
    # the browser, and the next reaction fails validation on the server.
    with db_session() as db:
        rows = db.execute(
            """SELECT m.* FROM swipe_decks d JOIN movies m ON m.id=d.movie_id
            WHERE d.session_id=? AND d.user_id=? ORDER BY d.position""",
            (session_id, user_id),
        ).fetchall()
    existing = [row_to_movie(row) for row in rows]
    unreleased_ids = [movie["id"] for movie in existing if not is_released(movie)]
    if unreleased_ids:
        with db_session() as db:
            placeholders = ",".join("?" for _ in unreleased_ids)
            db.execute(
                f"DELETE FROM swipe_decks WHERE session_id=? AND user_id=? AND movie_id IN ({placeholders})",
                (session_id, user_id, *unreleased_ids),
            )
            remaining = db.execute(
                "SELECT movie_id FROM swipe_decks WHERE session_id=? AND user_id=? ORDER BY position",
                (session_id, user_id),
            ).fetchall()
            # Shift first so the UNIQUE(session,user,position) constraint stays
            # valid while compacting positions after a removed card.
            db.execute(
                "UPDATE swipe_decks SET position=position+100000 WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            )
            db.executemany(
                "UPDATE swipe_decks SET position=? WHERE session_id=? AND user_id=? AND movie_id=?",
                [(position, session_id, user_id, row["movie_id"]) for position, row in enumerate(remaining, start=1)],
            )
        existing = [movie for movie in existing if movie["id"] not in set(unreleased_ids)]
    if len(existing) >= settings.swipe_count:
        return existing

    with db_session() as db:
        participant = db.execute(
            "SELECT disliked_genres FROM participants WHERE session_id=? AND user_id=?",
            (session_id, user_id),
        ).fetchone()
    excluded = set(normalize_genres(loads(participant["disliked_genres"], []))) if participant else set()
    # Older sessions can have been started when the product showed only eight
    # or twelve cards. Keep those reactions, then append enough new cards to
    # make both people reach the same current total.
    available = swipe_deck(
        session_id, user_id, max(settings.swipe_count * 2, settings.swipe_count + len(existing)),
        excluded_genres=excluded,
    )
    known_ids = {movie["id"] for movie in existing}
    additions = [movie for movie in available if movie["id"] not in known_ids]
    deck = existing + additions[: max(0, settings.swipe_count - len(existing))]
    with db_session() as db:
        db.executemany(
            "INSERT OR IGNORE INTO swipe_decks(session_id,user_id,movie_id,position) VALUES(?,?,?,?)",
            [(session_id, user_id, movie["id"], len(existing) + position) for position, movie in enumerate(additions[: max(0, settings.swipe_count - len(existing))], start=1)],
        )
    return deck


def get_deck(session_id: int, user_id: str) -> tuple[list[dict[str, Any]], int]:
    deck = _deck_for_user(session_id, user_id)
    with db_session() as db:
        done = {row[0] for row in db.execute("SELECT movie_id FROM swipes WHERE session_id=? AND user_id=?", (session_id, user_id)).fetchall()}
    return [movie for movie in deck if movie["id"] not in done], len(deck)


def save_swipe(session_id: int, user_id: str, movie_id: str, reaction: str) -> dict[str, Any]:
    deck = _deck_for_user(session_id, user_id)
    deck_ids = {movie["id"] for movie in deck}
    if movie_id not in deck_ids:
        raise ValueError("movie is not in this swipe deck")
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.execute(
            "INSERT OR REPLACE INTO swipes(session_id,user_id,movie_id,reaction,created_at) VALUES(?,?,?,?,?)",
            (session_id, user_id, movie_id, reaction, now),
        )
        progress = db.execute("SELECT COUNT(*) FROM swipes WHERE session_id=? AND user_id=?", (session_id, user_id)).fetchone()[0]
        total = len(deck)
        ready = int(total > 0 and progress >= total)
        db.execute("UPDATE participants SET progress=?,ready=? WHERE session_id=? AND user_id=?", (progress, ready, session_id, user_id))
    return {"progress": progress, "total": total, "ready": bool(ready)}


def both_ready(session_id: int) -> bool:
    with db_session() as db:
        rows = db.execute("SELECT user_id,ready FROM participants WHERE session_id=?", (session_id,)).fetchall()
    state = {row["user_id"]: bool(row["ready"]) for row in rows}
    return state.get("lera", False) and state.get("nikita", False)


def store_recommendations(session_id: int, recommendations: list[dict[str, Any]]) -> None:
    with db_session() as db:
        db.execute(
            """UPDATE sessions SET recommendations=?,
            status=CASE WHEN status IN ('choosing','recommended') THEN 'recommended' ELSE status END,
            updated_at=? WHERE id=?""",
            (dumps(recommendations), datetime.now().isoformat(timespec="seconds"), session_id),
        )


def choose_movie(session_id: int, exclude_current: bool = False) -> dict[str, Any]:
    with db_session() as db:
        session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise ValueError("session not found")
        rejected = loads(session["rejected_movies"], [])
        if exclude_current and session["selected_movie_id"] and session["selected_movie_id"] not in rejected:
            rejected.append(session["selected_movie_id"])
        candidates = []
        for item in loads(session["recommendations"], []):
            if item["id"] in rejected:
                continue
            current = get_movie(item["id"])
            if current and is_released(current):
                candidates.append(item)
        if not candidates:
            raise ValueError("no candidates left")
        top = candidates[: min(4, len(candidates))]
        weights = [max(1, int(item["match"] - 45)) ** 2 for item in top]
        selected = random.choices(top, weights=weights, k=1)[0]
        selected_at = datetime.now().isoformat(timespec="seconds")
        db.execute(
            """UPDATE sessions SET selected_movie_id=?,rejected_movies=?,status='selected',
            selected_at=?,updated_at=? WHERE id=?""",
            (selected["id"], dumps(rejected), selected_at, selected_at, session_id),
        )
    return selected


def choose_specific_recommendation(session_id: int, movie_id: str) -> dict[str, Any]:
    """Accept the couple's visible top pick without a second random draw."""
    with db_session() as db:
        session = db.execute("SELECT recommendations,rejected_movies FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise ValueError("session not found")
        rejected = set(loads(session["rejected_movies"], []))
        recommendations = loads(session["recommendations"], [])
        movie = get_movie(movie_id)
        if movie_id in rejected or movie_id not in {item.get("id") for item in recommendations} or not movie or not is_released(movie):
            raise ValueError("movie is not an available recommendation")
        selected_at = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "UPDATE sessions SET selected_movie_id=?,status='selected',selected_at=?,updated_at=? WHERE id=?",
            (movie_id, selected_at, selected_at, session_id),
        )
    return movie


def choose_saved_movie(session_id: int, movie_id: str) -> dict[str, Any]:
    """Choose a movie from the couple's shared watchlist."""
    movie = get_movie(movie_id)
    with db_session() as db:
        session = db.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        saved = db.execute("SELECT movie_id FROM watchlist WHERE movie_id=?", (movie_id,)).fetchone()
        if not session:
            raise ValueError("session not found")
        if not saved:
            raise ValueError("movie is not in watchlist")
        if not movie:
            raise ValueError("movie not found")
        if not is_released(movie):
            raise ValueError("movie is not released")
        selected_at = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "UPDATE sessions SET selected_movie_id=?,status='selected',selected_at=?,updated_at=? WHERE id=?",
            (movie_id, selected_at, selected_at, session_id),
        )
    return movie


def choose_catalog_movie(session_id: int, movie_id: str) -> dict[str, Any]:
    """Choose an existing local catalog result for the current evening."""
    movie = get_movie(movie_id)
    if not movie:
        raise ValueError("movie not found")
    if not is_released(movie):
        raise ValueError("movie is not released")
    with db_session() as db:
        session = db.execute("SELECT id,status FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or session["status"] == "completed":
            raise ValueError("session is not available")
        selected_at = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "UPDATE sessions SET selected_movie_id=?,status='selected',selected_at=?,updated_at=? WHERE id=?",
            (movie_id, selected_at, selected_at, session_id),
        )
    return movie


def confirm_watched(session_id: int) -> dict[str, Any]:
    with db_session() as db:
        session = db.execute("SELECT selected_movie_id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or not session["selected_movie_id"]:
            raise ValueError("movie not selected")
        now = datetime.now().isoformat(timespec="seconds")
        db.execute("INSERT OR IGNORE INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)", (session_id, session["selected_movie_id"], now))
        db.execute("DELETE FROM watchlist WHERE movie_id=?", (session["selected_movie_id"],))
        db.execute("UPDATE sessions SET status='completed',updated_at=? WHERE id=?", (now, session_id))
        history = db.execute("SELECT id FROM watch_history WHERE session_id=?", (session_id,)).fetchone()
    return {"history_id": history["id"], "movie": get_movie(session["selected_movie_id"])}


def decline_selected_movie(session_id: int) -> None:
    """Keep a declined option out of history and return to the short-list."""
    with db_session() as db:
        session = db.execute("SELECT selected_movie_id,rejected_movies FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or not session["selected_movie_id"]:
            raise ValueError("movie not selected")
        rejected = loads(session["rejected_movies"], [])
        if session["selected_movie_id"] not in rejected:
            rejected.append(session["selected_movie_id"])
        db.execute(
            "UPDATE sessions SET selected_movie_id=NULL,rejected_movies=?,status='recommended',selected_at=NULL,updated_at=? WHERE id=?",
            (dumps(rejected), datetime.now().isoformat(timespec="seconds"), session_id),
        )


def record_connection_restored(session_id: int) -> int:
    """Record one successful phone reconnection without storing device details."""
    with db_session() as db:
        changed = db.execute(
            "UPDATE sessions SET reconnect_count=reconnect_count+1 WHERE id=?",
            (session_id,),
        ).rowcount
        if not changed:
            raise ValueError("session not found")
        return db.execute(
            "SELECT reconnect_count FROM sessions WHERE id=?", (session_id,)
        ).fetchone()[0]


WATCHLIST_REASONS = frozenset({
    "На вечер, когда будет больше времени",
    "На другое настроение",
    "Хочется посмотреть вместе позже",
})


def _watchlist_today_context(db: Any) -> tuple[set[str], int | None]:
    """Return only the current evening's gentle sort signals.

    They rank saved choices; unlike recommendation constraints, they never
    remove anything from the couple's list.
    """
    session = db.execute(
        "SELECT id FROM sessions WHERE session_date=? ORDER BY id DESC LIMIT 1",
        (date.today().isoformat(),),
    ).fetchone()
    if not session:
        return set(), None
    participants = db.execute(
        "SELECT moods,max_runtime FROM participants WHERE session_id=?",
        (session["id"],),
    ).fetchall()
    moods = [mood for row in participants for mood in loads(row["moods"], [])]
    desired_genres = set().union(*(MOOD_GENRES.get(mood, set()) for mood in moods)) if moods else set()
    runtimes = [row["max_runtime"] for row in participants if row["max_runtime"] is not None]
    return desired_genres, min(runtimes) if runtimes else None


def _franchise_warning(db: Any, movie: Any, watched: set[str]) -> str | None:
    key, order = movie["franchise_key"], movie["franchise_order"]
    if not key or not order or order <= 1:
        return None
    earlier = db.execute(
        """SELECT id,title FROM movies WHERE franchise_key=?
        AND franchise_order IS NOT NULL AND franchise_order<? ORDER BY franchise_order""",
        (key, order),
    ).fetchall()
    missing = [row["title"] for row in earlier if row["id"] not in watched]
    if missing:
        return f"Сначала посмотрите: {', '.join(f'«{title}»' for title in missing)}."
    if len(earlier) < order - 1:
        return "Это продолжение. Предыдущей части нет в каталоге Tonight, поэтому не можем проверить просмотр."
    return None


def saved_movies() -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            "SELECT m.*,w.saved_at,w.saved_by,w.deferred_reason FROM watchlist w JOIN movies m ON m.id=w.movie_id ORDER BY w.saved_at DESC"
        ).fetchall()
        desired_genres, max_runtime = _watchlist_today_context(db)
        watched = {row["movie_id"] for row in db.execute("SELECT movie_id FROM watch_history").fetchall()}
        franchise_warnings = {row["id"]: _franchise_warning(db, row, watched) for row in rows}
    items = [
        {
            **row_to_movie(row),
            "saved_at": row["saved_at"],
            "saved_by": row["saved_by"],
            "deferred_reason": row["deferred_reason"],
            "franchise_warning": franchise_warnings[row["id"]],
        }
        for row in rows
    ]
    has_today_context = bool(desired_genres) or max_runtime is not None
    for item in items:
        mood_match = not desired_genres or bool(desired_genres.intersection(item["genres"]))
        time_match = max_runtime is None or (item["runtime"] is not None and item["runtime"] <= max_runtime)
        item["fits_tonight"] = bool(mood_match and time_match) if has_today_context else None
        item["mood_match"] = bool(mood_match) if desired_genres else None
        item["time_match"] = bool(time_match) if max_runtime is not None else None
    return sorted(
        items,
        key=lambda item: (
            item["fits_tonight"] is not True,
            item["time_match"] is False,
            item["mood_match"] is False,
        ),
        reverse=False,
    )


def save_movie_for_later(movie_id: str, user_id: str | None = None, deferred_reason: str | None = None) -> dict[str, Any]:
    movie = get_movie(movie_id)
    if not movie:
        raise ValueError("movie not found")
    if deferred_reason is not None and deferred_reason not in WATCHLIST_REASONS:
        raise ValueError("unknown watchlist reason")
    with db_session() as db:
        db.execute(
            "INSERT OR IGNORE INTO watchlist(movie_id,saved_at,saved_by,deferred_reason) VALUES(?,?,?,?)",
            (movie_id, datetime.now().isoformat(timespec="seconds"), user_id, deferred_reason),
        )
    return movie


def remove_saved_movie(movie_id: str) -> None:
    with db_session() as db:
        db.execute("DELETE FROM watchlist WHERE movie_id=?", (movie_id,))


def session_state(session_id: int, db: Any | None = None) -> dict[str, Any]:
    owns = db is None
    if owns:
        db = connect()
    try:
        row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("session not found")
        participants = db.execute("SELECT * FROM participants WHERE session_id=?", (session_id,)).fetchall()
        people = {
            user: {"joined": False, "progress": 0, "ready": False, "moods": [], "energy": None}
            for user in ("lera", "nikita")
        }
        for p in participants:
            people[p["user_id"]] = {"joined": True, "progress": p["progress"], "ready": bool(p["ready"]), "moods": loads(p["moods"], []), "energy": p["energy"]}
        selected = get_movie(row["selected_movie_id"]) if row["selected_movie_id"] else None
        rejected = set(loads(row["rejected_movies"], []))
        recommendations = []
        for item in loads(row["recommendations"], []):
            if item.get("id") in rejected or not item.get("id"):
                continue
            current = get_movie(item["id"])
            if not current or not is_released(current):
                continue
            item["poster_url"] = current["poster_url"]
            item["backdrop_url"] = current["backdrop_url"]
            item["trailer_url"] = current["trailer_url"]
            recommendations.append(item)
        # Recommendations are persisted snapshots. Refresh their media URLs so
        # a poster downloaded after matching immediately replaces cached art.
        recommendation_context = None
        if row["status"] in {"recommended", "selected", "completed"}:
            excluded: set[str] = set()
            runtimes: list[int] = []
            years: list[int] = []
            for p in participants:
                excluded.update(normalize_genres(loads(p["disliked_genres"], [])))
                if p["max_runtime"]: runtimes.append(p["max_runtime"])
                if p["min_year"]: years.append(p["min_year"])
            first = recommendations[0] if recommendations else {}
            recommendation_context = {
                "excluded_genres": sorted(excluded),
                "max_runtime": first.get("applied_max_runtime", min(runtimes) if runtimes else None),
                "min_year": first.get("applied_min_year", max(years) if years else None),
                "relaxed_constraints": first.get("relaxed_constraints", []),
                "method": "fair_joint_score",
            }
        return {
            "id": row["id"], "date": row["session_date"], "title": row["title"], "status": row["status"],
            "participants": people, "recommendations": recommendations, "selected": selected,
            "recommendation_context": recommendation_context,
        }
    finally:
        if owns:
            db.close()
