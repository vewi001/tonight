from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from backend.database.db import db_session, initialize


ROOT = Path(__file__).resolve().parents[1]
PERSONAL_PROFILE_NAMES = re.compile(
    r"\b(?:Лера|Леры|Лере|Леру|Лерой|Никита|Никиты|Никите|Никиту|Никитой)\b",
    re.IGNORECASE,
)
NEUTRAL_PROFILES = {
    "lera": ("Первый зритель", "🍿"),
    "nikita": ("Второй зритель", "🎬"),
}


def _profiles(path: Path | None = None) -> dict[str, tuple[str, str]]:
    with db_session(path) as db:
        rows = db.execute("SELECT id,name,emoji FROM users ORDER BY id").fetchall()
    return {row["id"]: (row["name"], row["emoji"]) for row in rows}


def test_new_database_uses_neutral_profile_labels():
    assert _profiles() == NEUTRAL_PROFILES


def test_existing_profile_labels_are_migrated_without_losing_history(tmp_path):
    database = tmp_path / "legacy.db"
    initialize(database)
    now = datetime.now().isoformat(timespec="seconds")
    with db_session(database) as db:
        db.execute("UPDATE users SET name='Лера',emoji='👩' WHERE id='lera'")
        db.execute("UPDATE users SET name='Никита',emoji='👨' WHERE id='nikita'")
        db.execute(
            "INSERT INTO movies(id,title,year,genres) VALUES(?,?,?,?)",
            ("legacy-film", "Старый фильм", 2020, "[]"),
        )
        session = db.execute(
            "INSERT INTO sessions(session_date,title,status,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("2026-10-01", "Старый вечер", "completed", now, now),
        )
        db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)",
            (session.lastrowid, "legacy-film", now),
        )

    initialize(database)

    assert _profiles(database) == NEUTRAL_PROFILES
    with db_session(database) as db:
        assert db.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0] == 1
        assert db.execute("SELECT title FROM sessions").fetchone()[0] == "Старый вечер"


def test_user_facing_sources_do_not_contain_personal_profile_names():
    files = [
        ROOT / "frontend" / "app.js",
        ROOT / "frontend" / "index.html",
        ROOT / "backend" / "recommendation" / "engine.py",
        ROOT / "launcher.py",
        ROOT / "README.md",
        ROOT / "PRODUCT_ROADMAP.md",
        *ROOT.glob("FEATURE_SPEC*.md"),
    ]
    matches: list[str] = []
    for path in files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PERSONAL_PROFILE_NAMES.search(line):
                matches.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert matches == []


def test_frontend_presents_two_neutral_viewer_profiles():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Первый зритель" in source
    assert "Второй зритель" in source
    assert "Пригласить второго зрителя" in source
