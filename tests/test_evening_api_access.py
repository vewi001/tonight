from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.sessions.service import active_session, session_access_code


REMOTE = ("192.168.1.50", 50000)


def test_remote_bootstrap_does_not_reveal_private_session_state_before_code():
    session = active_session(create=True)
    client = TestClient(app, client=REMOTE)

    active = client.get("/api/sessions/active")
    invite = client.get("/api/invite")

    assert active.status_code == 200
    assert active.json()["id"] == session["id"]
    assert "participants" not in active.json()
    assert "recommendations" not in active.json()
    assert "participants" not in invite.json()["session"]
    assert "recommendations" not in invite.json()["session"]
    assert "access_code" not in invite.json()


def test_remote_private_reads_and_writes_require_current_evening_header():
    session = active_session(create=True)
    code = session_access_code(session["id"])
    client = TestClient(app, client=REMOTE)
    preferences = {
        "user_id": "lera",
        "moods": ["cozy"],
        "energy": "low",
        "max_runtime": 120,
        "min_year": 2000,
        "disliked_genres": [],
    }

    denied_read = client.get(f"/api/sessions/{session['id']}")
    denied_history = client.get("/api/history")
    denied_write = client.post(f"/api/sessions/{session['id']}/preferences", json=preferences)

    headers = {"X-Tonight-Code": code}
    allowed_read = client.get(f"/api/sessions/{session['id']}", headers=headers)
    allowed_history = client.get("/api/history", headers=headers)
    allowed_write = client.post(f"/api/sessions/{session['id']}/preferences", json=preferences, headers=headers)

    assert [denied_read.status_code, denied_history.status_code, denied_write.status_code] == [403, 403, 403]
    assert [allowed_read.status_code, allowed_history.status_code, allowed_write.status_code] == [200, 200, 200]


def test_wrong_evening_header_is_rejected_without_mutating_preferences():
    session = active_session(create=True)
    client = TestClient(app, client=REMOTE)
    payload = {
        "user_id": "lera",
        "moods": ["cozy"],
        "energy": "low",
        "max_runtime": 120,
        "min_year": 2000,
        "disliked_genres": [],
    }

    response = client.post(
        f"/api/sessions/{session['id']}/preferences",
        json=payload,
        headers={"X-Tonight-Code": "000000"},
    )

    assert response.status_code == 403
    state = TestClient(app, client=("127.0.0.1", 50000)).get(f"/api/sessions/{session['id']}").json()
    assert state["participants"]["lera"]["joined"] is False


def test_frontend_attaches_evening_code_to_remote_api_requests():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "X-Tonight-Code" in source
    assert "isRemoteClient() && state.accessCode" in source
