from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from backend.database.db import db_session, initialize
from backend.main import app
from backend.sessions.service import active_session, choose_catalog_movie, decline_selected_movie, session_access_code


REMOTE = ("192.168.1.50", 50000)


def test_database_migrates_local_measurement_fields():
    with db_session() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)").fetchall()}
        row = db.execute("SELECT selected_at,reconnect_count FROM sessions LIMIT 1").fetchone()

    assert {"selected_at", "reconnect_count"}.issubset(columns)
    assert row is None


def test_existing_database_adds_measurement_fields_without_losing_evenings(tmp_path):
    database = tmp_path / "old-tonight.db"
    with sqlite3.connect(database) as db:
        db.execute(
            """CREATE TABLE sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_date TEXT NOT NULL,
                title TEXT NOT NULL, status TEXT NOT NULL, selected_movie_id TEXT,
                recommendations TEXT, rejected_movies TEXT, access_code TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        db.execute(
            """INSERT INTO sessions(
                session_date,title,status,access_code,created_at,updated_at
            ) VALUES('2026-10-07','Старый вечер','choosing','123456','2026-10-07','2026-10-07')"""
        )

    initialize(database)

    with sqlite3.connect(database) as db:
        row = db.execute("SELECT title,selected_at,reconnect_count FROM sessions").fetchone()
    assert row == ("Старый вечер", None, 0)


def test_empty_usage_summary_returns_zeros_without_inventing_choice_time():
    payload = TestClient(app).get("/api/usage-summary").json()["summary"]

    assert payload["evenings_started"] == 0
    assert payload["evenings_with_choice"] == 0
    assert payload["choice_rate_percent"] == 0
    assert payload["typical_choice_minutes"] is None
    assert payload["timed_evenings"] == 0


def test_selection_time_is_exact_and_rejected_choice_is_not_counted():
    session = active_session(create=True)

    choose_catalog_movie(session["id"], "arrival")
    with db_session() as db:
        selected_at = db.execute("SELECT selected_at FROM sessions WHERE id=?", (session["id"],)).fetchone()[0]

    assert selected_at

    decline_selected_movie(session["id"])
    with db_session() as db:
        selected_at_after_decline = db.execute("SELECT selected_at FROM sessions WHERE id=?", (session["id"],)).fetchone()[0]

    assert selected_at_after_decline is None


def test_local_usage_summary_aggregates_existing_evenings_without_external_telemetry():
    with db_session() as db:
        db.execute(
            """INSERT INTO sessions(
                session_date,title,status,selected_movie_id,recommendations,access_code,
                created_at,updated_at,selected_at,reconnect_count
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "2026-10-01", "Вечер 1", "completed", "arrival",
                '[{"id":"arrival","genres":["sci-fi","драма"]}]', "111111",
                "2026-10-01T20:00:00", "2026-10-01T20:20:00", "2026-10-01T20:10:00", 2,
            ),
        )
        first = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO participants(session_id,user_id,disliked_genres,joined_at) VALUES(?,?,?,?)",
            (first, "lera", '["хоррор"]', "2026-10-01T20:00:10"),
        )
        db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)",
            (first, "arrival", "2026-10-01T22:00:00"),
        )
        db.execute(
            """INSERT INTO sessions(
                session_date,title,status,recommendations,access_code,created_at,updated_at,reconnect_count
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                "2026-10-02", "Вечер 2", "abandoned",
                '[{"id":"alien","genres":["хоррор"]}]', "222222",
                "2026-10-02T20:00:00", "2026-10-02T20:03:00", 1,
            ),
        )
        second = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO participants(session_id,user_id,disliked_genres,joined_at) VALUES(?,?,?,?)",
            (second, "nikita", '["хоррор"]', "2026-10-02T20:00:10"),
        )

    response = TestClient(app).get("/api/usage-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "evenings_started": 2,
        "evenings_with_choice": 1,
        "choice_rate_percent": 50,
        "watched_confirmed": 1,
        "restarts": 1,
        "phone_reconnections": 3,
        "stop_genre_violations": 1,
        "typical_choice_minutes": 10,
        "timed_evenings": 1,
    }
    assert payload["privacy"] == {"local_only": True, "sent_to_developer": False}


def test_usage_summary_is_main_computer_only_and_remote_reconnect_is_counted_with_evening_code():
    session = active_session(create=True)
    code = session_access_code(session["id"])
    remote = TestClient(app, client=REMOTE)

    denied_summary = remote.get("/api/usage-summary", headers={"X-Tonight-Code": code})
    denied_reconnect = remote.post(f"/api/sessions/{session['id']}/connection-restored")
    accepted_reconnect = remote.post(
        f"/api/sessions/{session['id']}/connection-restored",
        headers={"X-Tonight-Code": code},
    )

    assert denied_summary.status_code == 403
    assert denied_reconnect.status_code == 403
    assert accepted_reconnect.status_code == 200
    with db_session() as db:
        assert db.execute("SELECT reconnect_count FROM sessions WHERE id=?", (session["id"],)).fetchone()[0] == 1


def test_frontend_explains_that_usage_summary_stays_local():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "/api/usage-summary" in source
    assert "Как проходят вечера" in source
    assert "Только на этом компьютере" in source
    assert "Ничего не отправляется разработчику" in source
    assert "api('/api/usage-summary').catch(() => null)" in source

