from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.recommendation.engine import _pair_profile


def _history() -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.execute(
            "INSERT INTO sessions(id,session_date,title,status,created_at,updated_at) VALUES(?,?,?,'completed',?,?)",
            (301, "2026-10-06", "Вечер", now, now),
        )
        return db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)",
            (301, "arrival", now),
        ).lastrowid


def test_evening_rating_is_optional_and_separate_from_movie_rating():
    history_id = _history()
    client = TestClient(app)
    assert client.post(f"/api/history/{history_id}/feedback", json={"user_id": "lera", "rating": 5}).status_code == 200

    response = client.post(f"/api/history/{history_id}/evening-feedback", json={"user_id": "lera", "fit": False})

    assert response.status_code == 200
    item = client.get("/api/history").json()["items"][0]
    assert item["ratings"]["lera"] == 5
    assert item["evening_feedback"]["lera"] is False
    assert item["evening_feedback"]["nikita"] is None


def test_frontend_makes_evening_rating_skippable():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Для совместного вечера подошло?" in source
    assert 'data-action="skip-evening-feedback"' in source


def test_pair_profile_uses_evening_feedback_without_changing_personal_ratings():
    history_id = _history()
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.executemany(
            "INSERT INTO feedback(history_id,user_id,rating,created_at) VALUES(?,?,?,?)",
            [(history_id, "lera", 5, now), (history_id, "nikita", 5, now)],
        )
        db.executemany(
            "INSERT INTO evening_feedback(history_id,user_id,fit,created_at) VALUES(?,?,?,?)",
            [(history_id, "lera", 0, now), (history_id, "nikita", 0, now)],
        )
        profile = _pair_profile(db)
    assert profile["sci-fi"] < 0.5
