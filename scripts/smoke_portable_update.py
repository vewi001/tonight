"""Isolated Windows EXE installation smoke; never touches the user's Tonight."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
# No real provider credentials are inherited by the isolated app/helper.
os.environ.update(TMDB_READ_TOKEN="", CATALOG_AUTO_UPDATE="0", TONIGHT_OPEN_BROWSER="0", TONIGHT_PORT="8771")

from backend.auto_update import AvailableUpdate
from backend.update_install import prepare_handoff


def stop_isolated(root: Path) -> None:
    executable = str(root / "Tonight.exe").replace("'", "''")
    command = f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -eq '{executable}' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
    subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, timeout=20,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)


def wait_http(version: str | None = None, timeout: float = 45) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8771/api/updates", timeout=2) as response:
                result = json.load(response)
            if version is None or result["current_version"] == version:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise AssertionError("The isolated updated app did not become ready")


def main() -> None:
    if os.name != "nt":
        raise SystemExit("This smoke requires Windows")
    build = Path(os.getenv("TONIGHT_SMOKE_BUILD", str(SOURCE / "work" / "auto-update-1.6.5-final"))).resolve()
    portable = build / "Tonight-portable-1.6.5"
    old = Path(os.getenv("TONIGHT_SMOKE_OLD_EXE", str(SOURCE / "work" / "release-1.6.4-public" / "Tonight-portable-1.6.4" / "Tonight.exe")))
    root = Path(tempfile.mkdtemp(prefix="exe-smoke-", dir=build))
    print(f"Isolated smoke: {root}", flush=True)
    shutil.copy2(old, root / "Tonight.exe")
    shutil.copy2(portable / "Обновить Tonight.exe", root / "Обновить Tonight.exe")
    (root / "data").mkdir()
    shutil.copy2(portable / "catalog" / "tonight.db", root / "data" / "tonight.db")
    with sqlite3.connect(root / "data" / "tonight.db") as db:
        movie = db.execute("SELECT id FROM movies LIMIT 1").fetchone()[0]
        db.execute("INSERT INTO users VALUES ('smoke-user','Test viewer','T','2026-10-09')")
        db.execute("INSERT INTO sessions (id,session_date,title,status,selected_movie_id,created_at,updated_at) VALUES (999,'2026-10-09','Smoke evening','watched',?,'2026-10-09','2026-10-09')", (movie,))
        db.execute("INSERT INTO watch_history (id,session_id,movie_id,watched_at) VALUES (999,999,?,'2026-10-09')", (movie,))
        db.execute("INSERT INTO feedback VALUES (999,'smoke-user',5,'2026-10-09')")
    environment = b"TONIGHT_HOST=127.0.0.1\nTONIGHT_PORT=8771\nTONIGHT_OPEN_BROWSER=0\nCATALOG_AUTO_UPDATE=0\nTMDB_READ_TOKEN=\n"
    (root / ".env").write_bytes(environment)
    (root / ".venv").mkdir()
    (root / ".venv" / "keep.txt").write_bytes(b"keep-runtime")
    (root / "data" / "keep-poster.jpg").write_bytes(b"keep-user-media")
    updates = root / "Updates"; updates.mkdir()
    package = updates / "Tonight-update-1.6.5.zip"
    shutil.copy2(build / package.name, package)
    digest = hashlib.file_digest(package.open("rb"), "sha256").hexdigest()
    offer = AvailableUpdate("1.6.5", package.name, package.stat().st_size, digest, "")
    before = hashlib.file_digest((root / "Tonight.exe").open("rb"), "sha256").hexdigest()
    app = subprocess.Popen([str(root / "Tonight.exe")], cwd=root, env=dict(os.environ),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    helper = None
    try:
        deadline = time.monotonic() + 40
        marker = root / "data" / "tonight-running.json"
        while not marker.exists() and time.monotonic() < deadline:
            if app.poll() is not None: raise AssertionError("Old portable exited before starting")
            time.sleep(0.25)
        pid = json.loads(marker.read_text(encoding="utf-8"))["pid"]
        if "--button" in sys.argv:
            wait_http("1.6.4")
            input("Browser button scenario ready at http://127.0.0.1:8771. Click update, then press Enter here.\n")
            app.wait(timeout=90)  # Must exit naturally through the real UI callback.
        else:
            helper = prepare_handoff(root, package, offer, pids=[pid, app.pid])
            print("Helper acknowledged readiness while old Tonight is running", flush=True)
            stop_isolated(root)
            app.wait(timeout=15)
        status = wait_http("1.6.5", timeout=90)
        if helper is not None:
            helper.wait(timeout=20)
            assert helper.returncode == 0
        assert status["install_supported"] is True
        assert (root / ".env").read_bytes() == environment
        assert (root / ".venv" / "keep.txt").read_bytes() == b"keep-runtime"
        assert (root / "data" / "keep-poster.jpg").read_bytes() == b"keep-user-media"
        assert (root / "rollback" / "previous" / "Tonight.exe").is_file()
        assert list((root / "data" / "backups").glob("before-update-*.db"))
        with sqlite3.connect(root / "data" / "tonight.db") as db:
            assert db.execute("SELECT rating FROM feedback WHERE history_id=999").fetchone()[0] == 5
            assert db.execute("SELECT count(*) FROM watch_history WHERE id=999").fetchone()[0] == 1
        after = hashlib.file_digest((root / "Tonight.exe").open("rb"), "sha256").hexdigest()
        assert before != after
        print("PASS: EXE replaced, 1.6.5 restarted; history, rating, env, runtime and media preserved; backup exists", flush=True)
        if "--hold-browser" in sys.argv:
            input("Browser smoke ready at http://127.0.0.1:8771. Press Enter to stop the isolated app.\n")
    finally:
        stop_isolated(root)
        if helper is not None and helper.poll() is None:
            helper.terminate(); helper.wait(timeout=15)


if __name__ == "__main__":
    main()
