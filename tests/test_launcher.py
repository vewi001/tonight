from __future__ import annotations

import socket

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

