"""Lightweight running marker shared by the launcher and standalone updater."""
import json
import os
from pathlib import Path

from backend.update_install import process_exists


def running_marker(root: Path) -> Path:
    return root / "data" / "tonight-running.json"


def write_running_marker(marker: Path, *, pid: int | None = None, port: int | None = None) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"pid": pid or os.getpid(), "parent_pid": os.getppid(), "port": port}), encoding="utf-8")


def is_running(marker: Path, *, process_exists=process_exists) -> bool:
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        pid = payload.get("pid")
    except (OSError, json.JSONDecodeError, AttributeError):
        return False
    return isinstance(pid, int) and not isinstance(pid, bool) and process_exists(pid)
