from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.sessions.service import active_session, session_access_code


def test_lan_join_requires_the_current_six_digit_evening_code():
    session = active_session(create=True)
    code = session_access_code(session["id"])
    client = TestClient(app, client=("192.168.1.50", 50000))

    denied = client.post(f"/api/sessions/{session['id']}/join", json={"user_id": "lera"})
    accepted = client.post(f"/api/sessions/{session['id']}/join", json={"user_id": "lera", "access_code": code})

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert len(code) == 6 and code.isdigit()
    assert "access_code" not in client.get(f"/api/sessions/{session['id']}").json()


def test_invited_phone_does_not_receive_the_code_from_invite_api():
    client = TestClient(app, client=("192.168.1.50", 50000))

    invite = client.get("/api/invite").json()

    assert "access_code" not in invite


def test_websocket_requires_the_evening_code_for_a_lan_client():
    session = active_session(create=True)
    code = session_access_code(session["id"])
    client = TestClient(app, client=("192.168.1.50", 50000))

    with client.websocket_connect(f"/ws/session/{session['id']}/lera?code={code}") as socket:
        assert socket.receive_json()["session"]["id"] == session["id"]

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/session/{session['id']}/lera"):
            pass
