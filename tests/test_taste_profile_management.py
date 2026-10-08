from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.recommendation.engine import _taste_profile
from backend.recommendation.taste_profile import exclude_genre, reset_profile


def _add_rated_arrival(session_id: int, rating: int = 5) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.execute(
            "INSERT INTO sessions(id,session_date,title,status,created_at,updated_at) VALUES(?,?,?,'completed',?,?)",
            (session_id, "2026-10-06", f"Вечер {session_id}", now, now),
        )
        history_id = db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)",
            (session_id, "arrival", now),
        ).lastrowid
        db.execute(
            "INSERT INTO feedback(history_id,user_id,rating,created_at) VALUES(?,?,?,?)",
            (history_id, "lera", rating, now),
        )


def test_mistaken_genre_can_be_removed_without_deleting_watch_history():
    _add_rated_arrival(101)
    _add_rated_arrival(102)
    client = TestClient(app)

    before = client.get("/api/taste").json()
    assert any(item["genre"] == "sci-fi" for item in before["profiles"]["lera"])

    response = client.delete("/api/taste/genres/sci-fi/lera")

    assert response.status_code == 200
    after = client.get("/api/taste").json()
    assert all(item["genre"] != "sci-fi" for item in after["profiles"]["lera"])
    assert client.get("/api/history").json()["items"]


def test_reset_profile_preserves_history_and_ratings_but_ignores_old_signals():
    _add_rated_arrival(101)
    _add_rated_arrival(102)
    client = TestClient(app)

    before = client.get("/api/taste").json()
    assert before["profiles"]["lera"]
    with db_session() as db:
        feedback_before = db.execute("SELECT COUNT(*) FROM feedback WHERE user_id='lera'").fetchone()[0]
        history_before = db.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0]

    response = client.post("/api/taste/reset/lera")

    assert response.status_code == 200
    after = client.get("/api/taste").json()
    assert after["profiles"]["lera"] == []
    with db_session() as db:
        assert db.execute("SELECT COUNT(*) FROM feedback WHERE user_id='lera'").fetchone()[0] == feedback_before
        assert db.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0] == history_before


def test_removed_or_reset_profile_signals_stop_affecting_recommendations():
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.execute(
            "INSERT INTO sessions(id,session_date,title,status,created_at,updated_at) VALUES(?,?,?,'choosing',?,?)",
            (201, "2026-10-06", "Выбор 201", now, now),
        )
        db.execute(
            "INSERT INTO swipes(session_id,user_id,movie_id,reaction,created_at) VALUES(?,?,?,?,?)",
            (201, "lera", "arrival", "love", now),
        )

    with db_session() as db:
        genres_before, _ = _taste_profile(db, 201, "lera")
    assert "sci-fi" in genres_before

    exclude_genre("lera", "sci-fi")
    with db_session() as db:
        genres_after_removal, _ = _taste_profile(db, 201, "lera")
    assert "sci-fi" not in genres_after_removal

    reset_profile("lera")
    with db_session() as db:
        genres_after_reset, keywords_after_reset = _taste_profile(db, 201, "lera")
    assert genres_after_reset == {}
    assert keywords_after_reset == {}


def test_frontend_offers_simple_profile_controls():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="remove-taste-genre"' in source
    assert 'data-action="reset-taste-profile"' in source
    assert "Удалить этот вывод" in source
    assert "Начать заново" in source
