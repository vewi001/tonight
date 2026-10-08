from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.recommendation.avoidance import add_avoidance, list_avoidances, remove_avoidance
from backend.recommendation.engine import recommend
from backend.sessions.service import active_session


def _session() -> int:
    return active_session(create=True)["id"]


def test_avoidance_can_be_added_listed_and_removed():
    rule = add_avoidance("lera", "arrival")

    assert rule["movie_id"] == "arrival"
    assert rule["title"] == "Прибытие"
    assert rule["genres"]
    assert list_avoidances("lera") == [rule]

    remove_avoidance(rule["id"], "lera")
    assert list_avoidances("lera") == []


def test_avoidance_lowers_close_match_without_blocking_whole_genre():
    sid = _session()
    before = {movie["id"]: movie for movie in recommend(sid, 100)}
    assert "arrival" in before

    add_avoidance("lera", "arrival")
    after = {movie["id"]: movie for movie in recommend(sid, 100)}

    assert after["arrival"]["person_scores"]["lera"] <= before["arrival"]["person_scores"]["lera"] - 0.15
    assert any("sci-fi" in movie["genres"] and movie["id"] != "arrival" for movie in after.values())


def test_avoid_similar_api_records_signal_and_declines_selected_movie():
    sid = _session()
    with db_session() as db:
        db.execute(
            "UPDATE sessions SET selected_movie_id='arrival',status='selected',updated_at=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), sid),
        )
    client = TestClient(app)

    response = client.post(
        f"/api/sessions/{sid}/avoid-similar",
        json={"user_id": "nikita", "movie_id": "arrival"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["status"] == "recommended"
    assert payload["session"]["selected"] is None
    assert payload["avoidance"]["movie_id"] == "arrival"
    assert list_avoidances("nikita")[0]["movie_id"] == "arrival"


def test_frontend_explains_and_allows_undoing_strong_rejections():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Не предлагать похожее" in source
    assert "Ослабим в будущих рекомендациях" in source
    assert 'data-action="confirm-avoid-similar"' in source
    assert 'data-action="remove-avoidance"' in source
