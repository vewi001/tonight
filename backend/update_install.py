"""Separate-process installation for Windows portable packages."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import httpx

from backend.auto_update import AvailableUpdate, UpdateError, VERSION
from backend.release import RecoveryError, ReleaseError, apply_release, read_release, rollback_previous


def process_exists(pid: int) -> bool:
    """Probe without signals: os.kill(pid, 0) is not read-only on Windows."""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        return ctypes.get_last_error() != 87  # invalid PID; access denied means alive
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0
    finally:
        kernel.CloseHandle(handle)


def wait_for_processes(pids: list[int], *, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while any(process_exists(pid) for pid in pids):
        if time.monotonic() >= deadline:
            raise UpdateError("Tonight ещё работает. Остановите его и повторите обновление.")
        time.sleep(0.2)


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    # These are internal bootloader settings of the parent executable.
    for key in list(environment):
        if key.startswith("_PYI_"):
            environment.pop(key)
    return environment


def _startup_health(port: int, version: str | None) -> bool:
    try:
        with httpx.Client(trust_env=False, timeout=1) as client:
            response = client.get(f"http://127.0.0.1:{port}/api/health")
            response.raise_for_status()
            payload = response.json()
        return isinstance(payload, dict) and payload.get("ok") is True and (version is None or payload.get("version") == version)
    except (httpx.HTTPError, ValueError):
        return False


def wait_for_startup(root: Path, process, *, timeout: float = 60) -> None:
    manifest = root / "tonight-release.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version") if manifest.exists() else None
    except (OSError, ValueError, AttributeError):
        raise OSError("Не удалось проверить версию Tonight") from None
    deadline = time.monotonic() + timeout
    while True:
        if process.poll() is not None:
            raise OSError("Новая версия Tonight завершилась до готовности")
        try:
            marker = json.loads((root / "data" / "tonight-running.json").read_text(encoding="utf-8"))
            pid, parent, port = marker.get("pid"), marker.get("parent_pid"), marker.get("port")
            owned = pid == process.pid or parent == process.pid
            # First-generation portable releases lack parent/port metadata.
            legacy = version is None and parent is None
            if legacy:
                port = int(os.getenv("TONIGHT_ACTIVE_PORT", os.getenv("TONIGHT_PORT", "8000")))
            if (owned or legacy) and isinstance(pid, int) and process_exists(pid) and isinstance(port, int) and 0 < port < 65536:
                if _startup_health(port, version):
                    return
        except (OSError, ValueError, AttributeError):
            pass
        if time.monotonic() >= deadline:
            raise OSError("Tonight не подтвердил готовность после перезапуска")
        time.sleep(0.2)


def restart_tonight(root: Path):
    process = subprocess.Popen([str(root / "Tonight.exe")], cwd=root, env=_clean_environment(),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        wait_for_startup(root, process)
    except OSError:
        if process.poll() is None:
            # Kill only this just-spawned process tree before touching locked EXEs.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                               timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                raise RecoveryError("Не удалось остановить новую версию. Остановите Tonight перед восстановлением файлов.") from None
        raise
    return process


def _validate_package(root: Path, package: Path, update: AvailableUpdate) -> Path:
    root = root.resolve()
    match = VERSION.fullmatch(update.version)
    if not match or update.name != f"Tonight-update-{update.version}.zip":
        raise UpdateError("Выберите пакет обновления Tonight.")
    expected = root / "Updates" / update.name
    if package.resolve() != expected.resolve() or not package.is_file():
        raise UpdateError("Не найден скачанный пакет обновления.")
    if package.stat().st_size != update.size:
        raise UpdateError("Скачанный пакет изменился. Скачайте его снова.")
    with package.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != update.sha256:
        raise UpdateError("Скачанный пакет изменился. Скачайте его снова.")
    release = read_release(package)
    if release.version != update.version or "Tonight.exe" not in release.files:
        raise UpdateError("Пакет не соответствует версии Tonight.")
    return root


def _copy_runner(root: Path) -> Path:
    updater = root / "Обновить Tonight.exe"
    if not updater.is_file():
        raise UpdateError("Не найден обновитель Tonight. Скачайте переносимую сборку.")
    runner = root / "Updates" / "runner" / uuid.uuid4().hex
    runner.mkdir(parents=True)
    executable = runner / updater.name
    shutil.copy2(updater, executable)
    return executable


def start_manual_runner(root: Path, *, pids: list[int], spawn=subprocess.Popen):
    root = root.resolve()
    executable = _copy_runner(root)
    command = [str(executable), "--manual-root", str(root)]
    for pid in pids:
        command.extend(["--wait-pid", str(pid)])
    return spawn(command, cwd=root, env=_clean_environment(),
                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def prepare_handoff(root: Path, package: Path, update: AvailableUpdate, *, pids: list[int], spawn=subprocess.Popen,
                    ready_timeout: float = 30):
    root = _validate_package(root, package, update)
    executable = _copy_runner(root)
    signal = executable.parent / "handoff.ready"
    command = [str(executable), "--auto-root", str(root), "--package", str(package.resolve()),
               "--version", update.version, "--sha256", update.sha256, "--size", str(update.size),
               "--ready-file", str(signal)]
    for pid in pids:
        command.extend(["--wait-pid", str(pid)])
    process = spawn(command, cwd=root, env=_clean_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + ready_timeout
    try:
        while process.poll() is None:
            if signal.is_file() and signal.read_text(encoding="utf-8") == "ready":
                pending = signal.with_suffix(".ack-tmp")
                pending.write_text("proceed", encoding="utf-8")
                os.replace(pending, signal.with_suffix(".proceed"))
                return process
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    except OSError:
        signal.with_suffix(".abort").touch()
        raise
    signal.with_suffix(".abort").touch()
    raise UpdateError("Не удалось запустить обновитель. Tonight продолжает работать.")


def accept_handoff(root: Path, package: Path, update: AvailableUpdate, signal: Path, *, timeout: float = 45) -> None:
    """The helper validates first; no installation before the parent's acknowledgement."""
    root = _validate_package(root, package, update)
    signal = signal.resolve()
    if signal.name != "handoff.ready" or signal.parent.parent != root / "Updates" / "runner":
        raise UpdateError("Неверный путь подтверждения обновления.")
    signal.write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + timeout
    while not signal.with_suffix(".abort").exists():
        acknowledgement = signal.with_suffix(".proceed")
        if acknowledgement.is_file() and acknowledgement.read_text(encoding="utf-8") == "proceed":
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    raise UpdateError("Запуск обновления отменён. Tonight не изменён.")


def install_downloaded(root: Path, package: Path, update: AvailableUpdate, *, pids: list[int],
                       wait: Callable = wait_for_processes, restart: Callable = restart_tonight, backup=None):
    wait(pids)
    root = root.resolve()
    try:
        _validate_package(root, package, update)
        release = apply_release(root, package, backup=backup)
    except RecoveryError:
        raise
    except (OSError, UpdateError, ReleaseError):
        restart(root)
        raise
    try:
        restart(root)
    except OSError:
        rollback_previous(root)
        restart(root)
        raise UpdateError("Не удалось открыть новую версию. Возвращена предыдущая версия Tonight.") from None
    return release
