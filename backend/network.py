from __future__ import annotations

import os
import socket

from backend.config import settings


def lan_ip() -> str:
    """Return the LAN address other devices should use for this computer."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def active_port() -> int:
    raw = os.getenv("TONIGHT_ACTIVE_PORT", str(settings.port))
    try:
        port = int(raw)
    except ValueError:
        return settings.port
    return port if 1 <= port <= 65535 else settings.port


def invite_url(address: str | None = None, port: int | None = None) -> str:
    return f"http://{address or lan_ip()}:{port or active_port()}/?join=1"
