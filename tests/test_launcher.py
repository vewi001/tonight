from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from launcher import available_port, is_running, server_config, write_running_marker


def test_launcher_finds_next_port_when_preferred_is_busy():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("0.0.0.0", 0))
    port = occupied.getsockname()[1]
    occupied.listen(1)
    try:
        selected = available_port(port)
        assert selected != port
        assert port < selected < port + 20
    finally:
        occupied.close()


def test_launcher_running_marker_only_accepts_live_process(tmp_path):
    marker = tmp_path / "tonight-running.json"

    write_running_marker(marker, pid=12345)

    assert not is_running(marker, process_exists=lambda pid: False)
    assert is_running(marker, process_exists=lambda pid: pid == 12345)


def test_launcher_does_not_require_console_streams_for_server_logging():
    assert server_config(8765).log_config is None


@pytest.mark.parametrize("recovery_phase", ["idle", "recovery_error"])
def test_portable_start_recovers_catalog_before_any_database_preparation(monkeypatch, tmp_path, recovery_phase):
    import launcher

    events = []

    def recover():
        events.append("recover")
        return {"phase": recovery_phase}

    async def offline_health():
        return {"available": False, "model_installed": False}

    monkeypatch.setattr(launcher, "catalog_updates", SimpleNamespace(recover=recover), raising=False)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "initialize", lambda: events.append("initialize"))
    monkeypatch.setattr(launcher, "bootstrap_catalog", lambda root: events.append("bootstrap"))
    monkeypatch.setattr(launcher, "seed_movies", lambda: events.append("seed") or 72)
    monkeypatch.setattr(launcher, "health", offline_health)
    monkeypatch.setattr(launcher, "available_port", lambda preferred: 8784)
    monkeypatch.setattr(launcher, "lan_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(launcher, "_say", lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher.qrcode.QRCode, "print_ascii", lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher.uvicorn, "Server", lambda config: SimpleNamespace(run=lambda: events.append("serve")))
    monkeypatch.setenv("TONIGHT_OPEN_BROWSER", "0")
    monkeypatch.setenv("TONIGHT_ACTIVE_PORT", "8784")

    launcher.main()

    assert events == ["recover", "initialize", "bootstrap", "seed", "serve"]
    assert launcher.local_url() is None
    assert not (tmp_path / "tonight-running.json").exists()

