from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from backend.api.realtime import manager
from backend.logging_filters import ExpectedWebSocketDisconnectFilter
from backend.main import app
from backend.sessions.service import active_session, ensure_participant, session_access_code


def _record(message: str, error: BaseException) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=(type(error), error, error.__traceback__),
    )


def test_windows_semaphore_timeout_is_treated_as_expected_disconnect():
    error = OSError("Превышен таймаут семафора")
    error.winerror = 121
    filter_ = ExpectedWebSocketDisconnectFilter()

    assert filter_.filter(_record("data transfer failed", error)) is False
    assert filter_.filter(_record("unrelated server failure", error)) is True


def test_websocket_can_disconnect_and_reconnect_to_same_evening():
    session_id = active_session(create=True)["id"]
    code = session_access_code(session_id)
    ensure_participant(session_id, "lera")
    client = TestClient(app)

    with client.websocket_connect(f"/ws/session/{session_id}/lera?code={code}") as socket:
        initial = socket.receive_json()
        assert initial["presence"]["lera"] is True
        socket.send_text("ping")
        assert socket.receive_json() == {"type": "pong"}

    assert manager.presence(session_id)["lera"] is False

    with client.websocket_connect(f"/ws/session/{session_id}/lera?code={code}") as socket:
        restored = socket.receive_json()
        assert restored["session"]["id"] == session_id
        assert restored["presence"]["lera"] is True
