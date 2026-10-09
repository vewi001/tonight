import hashlib
import os
import subprocess
import sys
import zipfile

import pytest

from backend.auto_update import AvailableUpdate, UpdateError
from backend.release import create_release_archive
from backend.update_install import accept_handoff, install_downloaded, process_exists, prepare_handoff


def fixture_package(tmp_path):
    root = tmp_path / "Tonight"; root.mkdir()
    (root / "Tonight.exe").write_bytes(b"old")
    (root / "Обновить Tonight.exe").write_bytes(b"updater")
    (root / ".env").write_bytes(b"private")
    source = tmp_path / "source"; source.mkdir(); (source / "Tonight.exe").write_bytes(b"new")
    path = create_release_archive(source, root / "Updates" / "Tonight-update-1.6.5.zip", version="1.6.5", files=["Tonight.exe"])
    update = AvailableUpdate("1.6.5", path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest(), "")
    return root, path, update


def test_process_probe_is_read_only_and_detects_exit():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.7)"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert process_exists(child.pid)
        assert child.poll() is None
        child.wait(timeout=5)
        assert not process_exists(child.pid)
    finally:
        if child.poll() is None: child.terminate(); child.wait(timeout=5)


def test_install_waits_then_rechecks_package_and_restarts(tmp_path):
    root, path, update = fixture_package(tmp_path); events = []
    result = install_downloaded(root, path, update, pids=[123], wait=lambda pids: events.append(("wait", pids)),
                               restart=lambda root: events.append(("restart", root)), backup=lambda root: events.append(("backup", root)))
    assert result.version == "1.6.5"
    assert [event[0] for event in events] == ["wait", "backup", "restart"]
    assert (root / "Tonight.exe").read_bytes() == b"new"
    assert (root / ".env").read_bytes() == b"private"


def test_modified_package_after_download_cannot_be_installed(tmp_path):
    root, path, update = fixture_package(tmp_path); path.write_bytes(b"tampered")
    starts = []
    with pytest.raises(UpdateError):
        install_downloaded(root, path, update, pids=[], wait=lambda pids: None, restart=lambda root: starts.append(root))
    assert (root / "Tonight.exe").read_bytes() == b"old"
    assert starts == [root.resolve()]


def test_installation_error_restarts_unchanged_program(tmp_path, monkeypatch):
    from backend.release import ReleaseError
    import backend.update_install as installer
    root, path, update = fixture_package(tmp_path); starts = []
    def fail(*args, **kwargs): raise ReleaseError("installation failed")
    monkeypatch.setattr(installer, "apply_release", fail)
    with pytest.raises(ReleaseError):
        install_downloaded(root, path, update, pids=[], wait=lambda pids: None, restart=lambda root: starts.append(root))
    assert starts == [root.resolve()]
    assert (root / "Tonight.exe").read_bytes() == b"old"


def test_failed_file_recovery_never_launches_partial_program(tmp_path, monkeypatch):
    from backend.release import RecoveryError
    import backend.update_install as installer
    root, path, update = fixture_package(tmp_path)
    def fail(*args, **kwargs): raise RecoveryError("restore failed")
    monkeypatch.setattr(installer, "apply_release", fail)
    with pytest.raises(RecoveryError):
        install_downloaded(root, path, update, pids=[], wait=lambda pids: None,
                           restart=lambda root: pytest.fail("partial program must not start"))


def test_timeout_leaves_program_unchanged(tmp_path):
    root, path, update = fixture_package(tmp_path)
    def wait(pids): raise UpdateError("Tonight ещё работает")
    with pytest.raises(UpdateError): install_downloaded(root, path, update, pids=[123], wait=wait)
    assert (root / "Tonight.exe").read_bytes() == b"old"


def test_handoff_uses_copy_outside_install_target_and_explicit_arguments(tmp_path):
    root, path, update = fixture_package(tmp_path); calls = []
    class Process:
        def poll(self): return None
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        from pathlib import Path
        Path(command[command.index("--ready-file") + 1]).write_text("ready", encoding="utf-8")
        return Process()
    prepare_handoff(root, path, update, pids=[123], spawn=spawn)
    command, options = calls[0]
    assert command[0] != str(root / "Обновить Tonight.exe")
    assert str(root / "Updates") in command[0]
    assert command[command.index("--auto-root") + 1] == str(root.resolve())
    assert "private" not in str(command)
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_handoff_failed_helper_never_authorizes_installation(tmp_path):
    root, path, update = fixture_package(tmp_path); calls = []
    class Process:
        def poll(self): return 1
    def spawn(command, **kwargs):
        calls.append(command)
        return Process()
    with pytest.raises(UpdateError, match="обновитель"):
        prepare_handoff(root, path, update, pids=[123], spawn=spawn)
    from pathlib import Path
    signal = Path(calls[0][calls[0].index("--ready-file") + 1])
    assert not signal.with_suffix(".proceed").exists()
    assert signal.with_suffix(".abort").is_file()
    assert (root / "Tonight.exe").read_bytes() == b"old"


def test_updater_import_does_not_start_or_import_main_server():
    result = subprocess.run([sys.executable, "-c", "import updater, sys; assert 'backend.main' not in sys.modules"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_handoff_timeout_cancels_late_helper(tmp_path):
    root, path, update = fixture_package(tmp_path)
    class Process:
        def poll(self): return None
    with pytest.raises(UpdateError):
        prepare_handoff(root, path, update, pids=[123], spawn=lambda *args, **kwargs: Process(), ready_timeout=0)
    signal = next((root / "Updates" / "runner").glob("*/handoff.abort"))
    with pytest.raises(UpdateError, match="отменён"):
        accept_handoff(root, path, update, signal.with_suffix(".ready"), timeout=0)
    assert (root / "Tonight.exe").read_bytes() == b"old"


def test_helper_revalidates_before_ready_and_requires_acknowledgement(tmp_path):
    root, path, update = fixture_package(tmp_path)
    signal = root / "Updates" / "runner" / "test" / "handoff.ready"
    signal.parent.mkdir(parents=True)
    with pytest.raises(UpdateError, match="отменён"):
        accept_handoff(root, path, update, signal, timeout=0)
    assert signal.is_file()
    signal.with_suffix(".proceed").write_text("proceed", encoding="utf-8")
    accept_handoff(root, path, update, signal, timeout=0)
    signal.unlink()
    path.write_bytes(b"tampered")
    with pytest.raises(UpdateError):
        accept_handoff(root, path, update, signal, timeout=0)
    assert not signal.exists()


def test_helper_rejects_empty_or_incomplete_acknowledgement(tmp_path):
    root, path, update = fixture_package(tmp_path)
    signal = root / "Updates" / "runner" / "test" / "handoff.ready"
    signal.parent.mkdir(parents=True)
    signal.with_suffix(".proceed").touch()
    with pytest.raises(UpdateError, match="отменён"):
        accept_handoff(root, path, update, signal, timeout=0)


def test_manual_updater_also_runs_from_copy_and_waits_for_original(tmp_path):
    from backend.update_install import start_manual_runner
    root, path, update = fixture_package(tmp_path); calls = []
    start_manual_runner(root, pids=[123, 456], spawn=lambda command, **options: calls.append(command))
    command = calls[0]
    assert command[0] != str(root / "Обновить Tonight.exe")
    assert command[command.index("--manual-root") + 1] == str(root.resolve())
    assert command.count("--wait-pid") == 2


def test_failed_restart_restores_old_program_and_retries_old_start(tmp_path):
    root, path, update = fixture_package(tmp_path); starts = []
    def restart(root):
        starts.append((root / "Tonight.exe").read_bytes())
        if len(starts) == 1: raise OSError("cannot launch")
    with pytest.raises(UpdateError, match="предыдущая"):
        install_downloaded(root, path, update, pids=[], wait=lambda pids: None, restart=restart, backup=lambda root: None)
    assert starts == [b"new", b"old"]
    assert (root / ".env").read_bytes() == b"private"


def test_startup_wait_requires_new_process_marker_and_correct_version(tmp_path, monkeypatch):
    import json
    import backend.update_install as installer
    root = tmp_path; (root / "data").mkdir()
    (root / "tonight-release.json").write_text(json.dumps({"version": "1.6.5"}))
    marker = root / "data" / "tonight-running.json"
    marker.write_text(json.dumps({"pid": 333, "parent_pid": 222, "port": 8771}))
    class Process:
        pid = 222
        def poll(self): return None
    monkeypatch.setattr(installer, "process_exists", lambda pid: True)
    calls = []
    monkeypatch.setattr(installer, "_startup_health", lambda port, version: calls.append((port, version)) or True)
    installer.wait_for_startup(root, Process(), timeout=0)
    assert calls == [(8771, "1.6.5")]
    marker.write_text(json.dumps({"pid": 333, "parent_pid": 111, "port": 8771}))
    with pytest.raises(OSError): installer.wait_for_startup(root, Process(), timeout=0)
    assert len(calls) == 1


def test_startup_exit_or_unresponsive_server_is_not_success(tmp_path, monkeypatch):
    import backend.update_install as installer
    class Exited:
        pid = 222
        def poll(self): return 1
    with pytest.raises(OSError): installer.wait_for_startup(tmp_path, Exited(), timeout=0)
    class Alive:
        pid = 222
        def poll(self): return None
    monkeypatch.setattr(installer, "_startup_health", lambda *args: False)
    with pytest.raises(OSError): installer.wait_for_startup(tmp_path, Alive(), timeout=0)


@pytest.mark.parametrize("reported,expected,result", [("1.6.5", "1.6.5", True), ("1.6.4", "1.6.5", False), (None, None, True)])
def test_startup_health_checks_exact_version_without_external_request(monkeypatch, reported, expected, result):
    import httpx
    import backend.update_install as installer
    original = httpx.Client
    urls = []
    def handle(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"ok": True, "version": reported})
    def client(**options):
        assert options["trust_env"] is False
        return original(transport=httpx.MockTransport(handle), **options)
    monkeypatch.setattr(installer.httpx, "Client", client)
    assert installer._startup_health(8771, expected) is result
    assert urls == ["http://127.0.0.1:8771/api/health"]


def test_failed_start_is_stopped_before_caller_can_restore_files(tmp_path, monkeypatch):
    import backend.update_install as installer
    commands = []
    class Process:
        pid = 222
        def poll(self): return None
        def wait(self, timeout): commands.append("exited")
        def terminate(self): commands.append("terminated")
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(installer.subprocess, "run", lambda command, **kwargs: commands.append(command))
    def fail(*args): raise OSError("startup failure")
    monkeypatch.setattr(installer, "wait_for_startup", fail)
    with pytest.raises(OSError): installer.restart_tonight(tmp_path)
    if os.name == "nt": assert commands[0] == ["taskkill", "/PID", "222", "/T", "/F"]
    assert commands[-1] == "exited"
