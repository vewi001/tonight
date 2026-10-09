from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import qrcode
import uvicorn

from backend.config import ROOT, settings
from backend.catalog_bundle import bootstrap_catalog
from backend.database.db import initialize
from backend.main import app, set_update_shutdown, updates
from backend.movies.seed import seed_movies
from backend.network import lan_ip
from backend.ollama.client import health
from backend.update_install import process_exists
from backend.process_state import running_marker, write_running_marker, is_running


_server: uvicorn.Server | None = None
_stop_requested = threading.Event()
_local_url: str | None = None


def _say(*args, **kwargs) -> None:
    if sys.stdout is not None:
        print(*args, **kwargs)


def local_url() -> str | None:
    return _local_url


def _process_exists(pid: int) -> bool:
    return process_exists(pid)


def stop() -> None:
    _stop_requested.set()
    if _server is not None:
        _server.should_exit = True


def server_config(port: int) -> uvicorn.Config:
    # PyInstaller's windowed build deliberately has no stdout/stderr. Uvicorn's
    # colourful default formatters call isatty() on those streams, so keep the
    # local technical log separate instead of requiring a console.
    return uvicorn.Config(app, host=settings.host, port=port, log_level="warning", log_config=None)


def available_port(preferred: int) -> int:
    """Keep double-click startup working even when another local app uses 8000."""
    for port in range(preferred, preferred + 20):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("0.0.0.0", port))
            probe.close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"Не найден свободный порт рядом с {preferred}")


def main() -> None:
    global _server, _local_url
    _stop_requested.clear()
    set_update_shutdown(stop)
    initialize()
    bootstrap_catalog(ROOT)
    count = seed_movies()
    ollama = asyncio.run(health())
    port = available_port(settings.port)
    os.environ["TONIGHT_ACTIVE_PORT"] = str(port)
    local_url = f"http://localhost:{port}"
    network_url = f"http://{lan_ip()}:{port}"
    line = "━" * 34
    _say(f"\n{line}\n🍿 TONIGHT\n{line}")
    _say("✓ Database ready")
    _say(f"✓ {count:,} movies".replace(",", " "))
    if ollama["available"] and ollama["model_installed"]:
        _say("✓ Ollama connected")
        _say(f"✓ {settings.ollama_model}")
    elif ollama["available"]:
        _say("○ Ollama connected — model missing")
        _say(f"  ollama pull {settings.ollama_model}")
    else:
        _say("○ Ollama offline — deterministic mode is ready")
    _say("✓ Tonight server running")
    if port != settings.port:
        _say(f"○ Порт {settings.port} занят — автоматически выбран {port}")
    _say(f"Этот компьютер → {local_url}")
    _say(f"Второе устройство → {network_url}")
    try:
        qr = qrcode.QRCode(border=1)
        qr.add_data(network_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        pass
    _say(f"{line}\n")
    _local_url = local_url
    if os.getenv("TONIGHT_OPEN_BROWSER", "1") != "0":
        threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()
    if _stop_requested.is_set():
        return
    marker = running_marker(ROOT)
    write_running_marker(marker, port=port)
    _server = uvicorn.Server(server_config(port))
    try:
        _server.run()
    finally:
        _server = None
        _local_url = None
        marker.unlink(missing_ok=True)
        set_update_shutdown(None)


if __name__ == "__main__":
    main()
