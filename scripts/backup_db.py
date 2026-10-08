"""Create a consistent SQLite backup, including data currently in WAL."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
source_path = ROOT / "data" / "tonight.db"
backup_dir = ROOT / "data" / "backups"

if not source_path.exists():
    raise SystemExit("База Tonight пока не создана.")

backup_dir.mkdir(parents=True, exist_ok=True)
target = backup_dir / f"tonight-{datetime.now():%Y%m%d-%H%M%S}.db"
source = sqlite3.connect(source_path)
try:
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
finally:
    source.close()

print(target.relative_to(ROOT))
