from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.recommendation.weekly import weekly_picks


def test_weekly_picks_are_local_stable_and_skip_watched_movies():
    with db_session() as db:
        db.execute(
            "INSERT INTO sessions(id,session_date,title,status,created_at,updated_at) VALUES(?,?,?,'completed',datetime('now'),datetime('now'))",
            (701, "2026-10-07", "Прошлый вечер"),
        )
        db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,datetime('now'))",
            (701, "arrival"),
        )

    first = weekly_picks(reference_day=date(2026, 10, 7))
    second = weekly_picks(reference_day=date(2026, 10, 9))

    assert len(first) == 5
    assert len({item["id"] for item in first}) == 5
    assert "arrival" not in {item["id"] for item in first}
    assert [item["id"] for item in second] == [item["id"] for item in first]
    assert all(item["weekly_reason"] for item in first)


def test_weekly_picks_do_not_offer_a_known_unwatched_sequel():
    with db_session() as db:
        db.execute("UPDATE movies SET franchise_key='weekly-test',franchise_order=1 WHERE id='arrival'")
        db.execute("UPDATE movies SET franchise_key='weekly-test',franchise_order=2 WHERE id='ex-machina'")

    picks = weekly_picks(reference_day=date(2026, 10, 7))

    assert "ex-machina" not in {item["id"] for item in picks}


def test_weekly_picks_exclude_a_movie_with_a_future_official_release_date():
    with db_session() as db:
        db.execute("UPDATE movies SET release_date='2099-01-01' WHERE id='arrival'")

    picks = weekly_picks(reference_day=date(2026, 10, 7))

    assert "arrival" not in {item["id"] for item in picks}


def test_weekly_picks_regenerate_when_every_stored_movie_becomes_unreleased():
    reference_day = date(2026, 10, 7)
    previous = weekly_picks(reference_day=reference_day)
    previous_ids = {item["id"] for item in previous}
    with db_session() as db:
        db.executemany(
            "UPDATE movies SET release_date='2099-01-01' WHERE id=?",
            [(movie_id,) for movie_id in previous_ids],
        )

    regenerated = weekly_picks(reference_day=reference_day)

    assert len(regenerated) == 5
    assert previous_ids.isdisjoint({item["id"] for item in regenerated})


def test_weekly_picks_are_available_in_the_app_without_notifications():
    client = TestClient(app)

    response = client.get("/api/weekly-picks")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 5
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'data-view="weekly"' in source
    assert "Tonight ничего не отправляет сам" in source
