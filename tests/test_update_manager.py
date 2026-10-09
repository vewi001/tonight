from pathlib import Path

import pytest

import backend.auto_update as module
from backend.auto_update import AvailableUpdate, UpdateError, UpdateManager


def available():
    return AvailableUpdate("1.6.5", "Tonight-update-1.6.5.zip", 100, "0" * 64, "https://github.com/file")


def test_background_checks_are_cached_but_manual_check_can_refresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "fetch_latest_update", lambda version: calls.append(version) or available())
    manager = UpdateManager(tmp_path, "1.6.4")
    assert manager.check()["available_version"] == "1.6.5"
    manager.check(); manager.check(force=True)
    assert calls == ["1.6.4", "1.6.4"]


def test_source_install_is_not_allowed_and_status_contains_no_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "fetch_latest_update", lambda version: available())
    manager = UpdateManager(tmp_path, "1.6.4")
    manager.check()
    with pytest.raises(UpdateError, match="переносимой"): manager.reserve_download()
    assert str(tmp_path) not in str(manager.status())


def test_one_download_at_a_time_and_checked_file_becomes_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "fetch_latest_update", lambda version: available())
    def download(update, destination, *, progress):
        progress(100, 100)
        return destination / update.name
    monkeypatch.setattr(module, "download_update", download)
    manager = UpdateManager(tmp_path, "1.6.4", install_supported=True)
    manager.check(); update = manager.reserve_download()
    with pytest.raises(UpdateError, match="уже"): manager.reserve_download()
    assert manager.download_reserved(update) == tmp_path / "Updates" / update.name
    assert manager.status()["phase"] == "ready"
    assert manager.status()["download_bytes"] == 100
    with pytest.raises(UpdateError, match="уже"): manager.reserve_download()


def test_download_failure_can_be_retried_without_losing_offer(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "fetch_latest_update", lambda version: available())
    def fail(*args, **kwargs): raise UpdateError("Не удалось скачать")
    monkeypatch.setattr(module, "download_update", fail)
    manager = UpdateManager(tmp_path, "1.6.4", install_supported=True)
    manager.check(); update = manager.reserve_download()
    assert manager.download_reserved(update) is None
    assert manager.status()["phase"] == "error"
    assert manager.reserve_download() == update


def test_app_job_blocks_other_manager_until_failure(tmp_path,monkeypatch):
    from backend.update_guard import acquire_update_lease, UpdateBusyError
    monkeypatch.setattr(module,'fetch_latest_update',lambda version:available())
    first = UpdateManager(tmp_path,'1.6.4',install_supported=True)
    second = UpdateManager(tmp_path,'1.6.4',install_supported=True)
    first.check(); second.check()
    first.reserve_download()
    with pytest.raises(UpdateBusyError):
        acquire_update_lease(tmp_path)
    with pytest.raises(UpdateError):
        second.reserve_download()
    assert second.status()['phase']=='available'
    first.fail('Failure')
    second.reserve_download()
    second.fail('Cleanup')
