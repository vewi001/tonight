"""Local-only aggregate product checks derived from the user's Tonight database."""
from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any

from backend.database.db import db_session, loads
from backend.movies.genres import normalize_genres


def _choice_minutes(created_at: str, selected_at: str) -> float | None:
    try:
        elapsed = (datetime.fromisoformat(selected_at) - datetime.fromisoformat(created_at)).total_seconds()
    except (TypeError, ValueError):
        return None
    return max(0.0, elapsed / 60)


def _stop_genre_violations(db: Any, sessions: list[Any]) -> int:
    violations = 0
    for session in sessions:
        rows = db.execute(
            "SELECT disliked_genres FROM participants WHERE session_id=?",
            (session["id"],),
        ).fetchall()
        stopped = {
            genre
            for row in rows
            for genre in normalize_genres(loads(row["disliked_genres"], []))
        }
        if not stopped:
            continue
        seen: set[str] = set()
        for recommendation in loads(session["recommendations"], []):
            movie_id = str(recommendation.get("id", ""))
            if not movie_id or movie_id in seen:
                continue
            seen.add(movie_id)
            offered_genres = set(normalize_genres(recommendation.get("genres", [])))
            if stopped.intersection(offered_genres):
                violations += 1
    return violations


def usage_summary() -> dict[str, Any]:
    with db_session() as db:
        sessions = db.execute(
            """SELECT s.id,s.status,s.recommendations,s.created_at,s.selected_at,s.reconnect_count
            FROM sessions s
            WHERE s.status IN ('abandoned','selected','completed')
               OR s.selected_movie_id IS NOT NULL
               OR EXISTS(SELECT 1 FROM participants p WHERE p.session_id=s.id)
               OR EXISTS(SELECT 1 FROM swipes w WHERE w.session_id=s.id)
            ORDER BY s.id"""
        ).fetchall()
        watched = db.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0]
        stop_violations = _stop_genre_violations(db, sessions)

    durations = [
        value
        for session in sessions
        if session["selected_at"]
        for value in [_choice_minutes(session["created_at"], session["selected_at"])]
        if value is not None
    ]
    started = len(sessions)
    with_choice = sum(session["status"] in {"selected", "completed"} for session in sessions)
    typical = round(median(durations)) if durations else None
    return {
        "summary": {
            "evenings_started": started,
            "evenings_with_choice": with_choice,
            "choice_rate_percent": round(with_choice * 100 / started) if started else 0,
            "watched_confirmed": watched,
            "restarts": sum(session["status"] == "abandoned" for session in sessions),
            "phone_reconnections": sum(session["reconnect_count"] or 0 for session in sessions),
            "stop_genre_violations": stop_violations,
            "typical_choice_minutes": typical,
            "timed_evenings": len(durations),
        },
        "privacy": {"local_only": True, "sent_to_developer": False},
    }
