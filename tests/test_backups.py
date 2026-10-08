from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.backups import create_backup, import_backup, list_backups, restore_backup
from backend.database.db import connect, db_session, initialize
from backend.main import app


def test_restore_replaces_database_only_after_creating_a_safety_copy(tmp_path):
    database = tmp_path / "tonight.db"
    backup_dir = tmp_path / "backups"
    initialize(database)
    with connect(database) as db:
        db.execute("INSERT INTO app_meta(key,value) VALUES('before','saved')")

    exported = create_backup(database, backup_dir)
    with connect(database) as db:
        db.execute("INSERT INTO app_meta(key,value) VALUES('after','temporary')")

    safety = restore_backup(database, backup_dir, exported.name)

    with connect(database) as db:
        assert db.execute("SELECT value FROM app_meta WHERE key='before'").fetchone()[0] == "saved"
        assert db.execute("SELECT value FROM app_meta WHERE key='after'").fetchone() is None
    assert safety.exists()
    assert {item["name"] for item in list_backups(backup_dir)} >= {exported.name, safety.name}


def test_restore_rejects_a_file_that_is_not_a_tonight_backup(tmp_path):
    database = tmp_path / "tonight.db"
    backup_dir = tmp_path / "backups"
    initialize(database)
    invalid = backup_dir / "not-tonight.db"
    backup_dir.mkdir()
    sqlite3.connect(invalid).close()

    with pytest.raises(ValueError, match="Tonight"):
        restore_backup(database, backup_dir, invalid.name)


def test_imported_backup_is_validated_before_becoming_available_to_restore(tmp_path):
    database = tmp_path / "tonight.db"
    backup_dir = tmp_path / "backups"
    initialize(database)
    with connect(database) as db:
        db.execute("INSERT INTO app_meta(key,value) VALUES('from_export','saved')")
    exported = create_backup(database, backup_dir)
    incoming = tmp_path / "Tonight-data.db"
    incoming.write_bytes(exported.read_bytes())

    imported = import_backup(backup_dir, incoming)

    assert imported.parent == backup_dir
    assert imported.name.startswith("imported-")
    assert imported in [backup_dir / item["name"] for item in list_backups(backup_dir)]
    with connect(database) as db:
        db.execute("INSERT INTO app_meta(key,value) VALUES('temporary','change')")
    restore_backup(database, backup_dir, imported.name)
    with connect(database) as db:
        assert db.execute("SELECT value FROM app_meta WHERE key='from_export'").fetchone()[0] == "saved"
        assert db.execute("SELECT value FROM app_meta WHERE key='temporary'").fetchone() is None


def test_import_rejects_invalid_file_without_leaving_a_restorable_copy(tmp_path):
    backup_dir = tmp_path / "backups"
    incoming = tmp_path / "not-tonight.db"
    incoming.write_bytes(b"not a sqlite database")

    with pytest.raises(ValueError, match="Tonight"):
        import_backup(backup_dir, incoming)

    assert list_backups(backup_dir) == []


def test_import_rejects_sqlite_with_tonight_table_names_but_wrong_schema(tmp_path):
    backup_dir = tmp_path / "backups"
    incoming = tmp_path / "wrong-schema.db"
    with sqlite3.connect(incoming) as db:
        for table in ("users", "movies", "sessions", "watch_history", "feedback"):
            db.execute(f"CREATE TABLE {table}(dummy TEXT)")

    with pytest.raises(ValueError, match="Tonight"):
        import_backup(backup_dir, incoming)

    assert list_backups(backup_dir) == []


def test_api_restores_a_downloaded_export_only_after_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    with db_session() as db:
        db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('exported','yes')")
    client = TestClient(app, client=("127.0.0.1", 50000))
    created = client.post("/api/backup")
    assert created.status_code == 200
    name = created.json()["name"]
    downloaded = client.get(f"/api/backups/{name}/download")
    assert downloaded.status_code == 200
    with db_session() as db:
        db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('after_export','temporary')")

    not_confirmed = client.post("/api/backups/import", content=downloaded.content)
    assert not_confirmed.status_code == 400
    restored = client.post("/api/backups/import?confirmed=true", content=downloaded.content)
    assert restored.status_code == 200
    with db_session() as db:
        assert db.execute("SELECT value FROM app_meta WHERE key='exported'").fetchone()[0] == "yes"
        assert db.execute("SELECT value FROM app_meta WHERE key='after_export'").fetchone() is None
    assert restored.json()["safety_backup"].startswith("before-restore-")


def test_backup_endpoints_are_not_available_to_other_lan_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    backup_dir = tmp_path / "data" / "backups"
    backup_dir.mkdir(parents=True)
    (backup_dir / "private.db").write_bytes(b"private data")
    client = TestClient(app, client=("192.168.1.50", 50000))

    responses = [
        client.post("/api/backup"),
        client.get("/api/backups"),
        client.get("/api/backups/private.db/download"),
        client.post("/api/backups/private.db/restore", json={"confirmed": True}),
        client.post("/api/backups/import?confirmed=true", content=b"private data"),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403]
    assert (backup_dir / "private.db").read_bytes() == b"private data"


def test_frontend_makes_backup_and_restore_actions_explicit():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="create-backup"' in source
    assert 'data-action="restore-backup"' in source
    assert "страховочную копию" in source
    assert "Последняя копия:" in source
    assert 'data-action="export-data"' in source
    assert 'data-backup-import' in source
    assert "isRemoteClient() ? null : api('/api/backups')" in source
