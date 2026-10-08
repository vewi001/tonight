from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from backend import main
from backend.api.realtime import ConnectionManager
from backend.database.db import db_session, initialize
from backend.main import app
from backend.privacy import PERSONAL_TABLES, delete_personal_data


CONFIRMATION = "УДАЛИТЬ ВСЕ ДАННЫЕ"


def _fill_personal_data(database):
    now = datetime.now().isoformat(timespec="seconds")
    with db_session(database) as db:
        db.execute(
            "INSERT INTO movies(id,title,year,genres) VALUES(?,?,?,?)",
            ("privacy-film", "Фильм для проверки", 2020, "[]"),
        )
        session_id = db.execute(
            "INSERT INTO sessions(session_date,title,status,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("2026-10-07", "Личный вечер", "completed", now, now),
        ).lastrowid
        db.execute(
            "INSERT INTO participants(session_id,user_id,joined_at,ready) VALUES(?,?,?,1)",
            (session_id, "lera", now),
        )
        db.execute(
            "INSERT INTO swipes(session_id,user_id,movie_id,reaction,created_at) VALUES(?,?,?,?,?)",
            (session_id, "lera", "privacy-film", "love", now),
        )
        db.execute(
            "INSERT INTO swipe_decks(session_id,user_id,movie_id,position) VALUES(?,?,?,?)",
            (session_id, "lera", "privacy-film", 0),
        )
        history_id = db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)",
            (session_id, "privacy-film", now),
        ).lastrowid
        db.execute(
            "INSERT INTO feedback(history_id,user_id,rating,created_at) VALUES(?,?,?,?)",
            (history_id, "lera", 5, now),
        )
        db.execute(
            "INSERT INTO evening_feedback(history_id,user_id,fit,created_at) VALUES(?,?,?,?)",
            (history_id, "lera", 1, now),
        )
        db.execute(
            "INSERT INTO watchlist(movie_id,saved_at,saved_by,deferred_reason) VALUES(?,?,?,?)",
            ("privacy-film", now, "lera", "На другое настроение"),
        )
        db.execute(
            "INSERT INTO weekly_picks(week_start,position,movie_id,reason,generated_at) VALUES(?,?,?,?,?)",
            ("2026-10-05", 1, "privacy-film", "Подходит вам", now),
        )
        db.execute(
            "INSERT INTO avoid_similar(user_id,movie_id,genres,keywords,created_at) VALUES(?,?,?,?,?)",
            ("lera", "privacy-film", "[]", "[]", now),
        )
        db.execute(
            "INSERT INTO taste_genre_exclusions(user_id,genre,created_at) VALUES(?,?,?)",
            ("lera", "драма", now),
        )
        db.execute(
            "INSERT INTO taste_profile_resets(user_id,reset_at) VALUES(?,?)",
            ("lera", now),
        )
        db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('catalog-marker','keep')")
    return session_id


def test_delete_personal_data_clears_every_personal_table_but_keeps_catalog(tmp_path):
    database = tmp_path / "tonight.db"
    backup_dir = tmp_path / "backups"
    external_export = tmp_path / "downloaded-elsewhere.db"
    initialize(database)
    _fill_personal_data(database)
    backup_dir.mkdir()
    (backup_dir / "tonight-copy.db").write_bytes(b"private backup")
    external_export.write_bytes(b"outside Tonight")

    result = delete_personal_data(database, backup_dir)

    assert result["backups_deleted"] == 1
    assert list(backup_dir.iterdir()) == []
    assert external_export.read_bytes() == b"outside Tonight"
    with db_session(database) as db:
        assert all(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0 for table in PERSONAL_TABLES)
        assert db.execute("SELECT title FROM movies WHERE id='privacy-film'").fetchone()[0] == "Фильм для проверки"
        assert db.execute("SELECT value FROM app_meta WHERE key='catalog-marker'").fetchone()[0] == "keep"
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    repeated = delete_personal_data(database, backup_dir)
    assert repeated["deleted_rows"] == 0
    assert repeated["backups_deleted"] == 0


def test_delete_api_rejects_remote_clients_and_wrong_confirmation(tmp_path):
    session_id = _fill_personal_data(main.settings.db_path)
    main_computer = TestClient(app, client=("127.0.0.1", 50000))
    other_device = TestClient(app, client=("192.168.1.50", 50000))

    remote = other_device.post("/api/privacy/delete", json={"confirmation": CONFIRMATION})
    wrong_phrase = main_computer.post("/api/privacy/delete", json={"confirmation": "удалить"})

    assert remote.status_code == 403
    assert wrong_phrase.status_code == 400
    with db_session() as db:
        assert db.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone() is not None


def test_delete_api_removes_local_data_and_backups_after_exact_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _fill_personal_data(main.settings.db_path)
    backup_dir = tmp_path / "data" / "backups"
    backup_dir.mkdir(parents=True)
    (backup_dir / "local-copy.db").write_bytes(b"private backup")
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post("/api/privacy/delete", json={"confirmation": CONFIRMATION})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert list(backup_dir.iterdir()) == []
    with db_session() as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM movies").fetchone()[0] > 0


def test_privacy_reset_event_closes_connected_clients():
    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = None

        async def accept(self):
            pass

        async def send_json(self, payload):
            self.messages.append(payload)

        async def close(self, code=1000):
            self.closed = code

    manager = ConnectionManager()
    socket = Socket()

    async def scenario():
        await manager.connect(42, "lera", socket)
        await manager.close_sessions([42], {"type": "privacy_reset"})
        # The websocket handler runs its normal finally block after close.
        manager.disconnect(42, "lera", socket)

    asyncio.run(scenario())

    assert socket.messages == [{"type": "privacy_reset"}]
    assert socket.closed == 1000
    assert 42 not in manager.connections


def test_frontend_explains_and_guards_full_data_deletion():
    source = (main.ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "Удалить личные данные" in source
    assert "УДАЛИТЬ ВСЕ ДАННЫЕ" in source
    assert "Скачанные ранее копии" in source
    assert 'data-action="open-privacy-delete"' in source
    assert 'data-action="confirm-privacy-delete"' in source


def test_plain_language_privacy_notice_covers_local_storage_network_and_control():
    notice = (main.ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    frontend = (main.ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "хранятся на вашем компьютере" in notice
    assert "не отправляет историю" in notice
    assert "Экспорт" in notice and "Удаление" in notice
    assert "TMDB" in notice
    assert "Как Tonight обращается с данными" in frontend
