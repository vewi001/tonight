from __future__ import annotations

from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.movies.franchises import franchises


def _series() -> int:
    with db_session() as db:
        db.execute("UPDATE movies SET franchise_key='test-series',franchise_order=1 WHERE id='arrival'")
        db.execute("UPDATE movies SET franchise_key='test-series',franchise_order=2 WHERE id='ex-machina'")
        db.execute(
            "INSERT INTO sessions(id,session_date,title,status,created_at,updated_at) VALUES(?,?,?,'completed',datetime('now'),datetime('now'))",
            (801, "2026-10-07", "Вечер"),
        )
    return 801


def test_franchise_page_marks_watched_parts_and_suggests_next_available_part():
    session_id = _series()

    before = next(group for group in franchises() if group["key"] == "test-series")
    assert [part["id"] for part in before["parts"]] == ["arrival", "ex-machina"]
    assert [part["watched"] for part in before["parts"]] == [False, False]
    assert before["next_movie"]["id"] == "arrival"

    with db_session() as db:
        db.execute("INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,datetime('now'))", (session_id, "arrival"))

    after = next(group for group in franchises() if group["key"] == "test-series")
    assert after["parts"][0]["watched"] is True
    assert after["next_movie"]["id"] == "ex-machina"


def test_future_franchise_part_is_not_offered_as_the_next_movie():
    session_id = _series()
    with db_session() as db:
        db.execute("UPDATE movies SET release_date='2099-01-01' WHERE id='ex-machina'")
        db.execute("INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,datetime('now'))", (session_id, "arrival"))

    group = next(item for item in franchises() if item["key"] == "test-series")

    future_part = next(item for item in group["parts"] if item["id"] == "ex-machina")
    assert future_part["released"] is False
    assert future_part["available"] is False
    assert group["next_movie"] is None


def test_franchise_page_is_exposed_without_making_the_series_mandatory():
    _series()
    client = TestClient(app)

    response = client.get("/api/franchises")

    assert response.status_code == 200
    assert any(group["key"] == "test-series" for group in response.json()["items"])
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'data-view="franchises"' in source
    assert "не обязательный маршрут" in source
    assert "Ещё не вышел в прокат" in source
