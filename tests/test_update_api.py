from fastapi.testclient import TestClient
import pytest

from backend import main
from backend.auto_update import AvailableUpdate, UpdateManager
import backend.auto_update as auto


@pytest.fixture
def manager(tmp_path, monkeypatch):
    manager = UpdateManager(tmp_path, "1.6.4", install_supported=True)
    monkeypatch.setattr(main, "updates", manager)
    monkeypatch.setattr(auto, "fetch_latest_update", lambda version: AvailableUpdate("1.6.5", "Tonight-update-1.6.5.zip", 100, "0" * 64, ""))
    return manager


def test_main_computer_can_check_public_update_state(manager):
    with TestClient(main.app) as client:
        result = client.post("/api/updates/check", headers={"X-Tonight-Update": "1"})
        assert result.status_code == 200
        assert result.json()["available_version"] == "1.6.5"
        assert client.get("/api/updates").json()["install_supported"] is True


def test_phone_cannot_check_or_install_even_with_evening_code(manager):
    with TestClient(main.app, client=("192.168.1.20", 1234)) as client:
        assert client.get("/api/updates").status_code == 403
        assert client.post("/api/updates/check", headers={"X-Tonight-Update": "1"}).status_code == 403
        assert client.post("/api/updates/install", headers={"X-Tonight-Update": "1"}).status_code == 403


@pytest.mark.parametrize("headers", [{}, {"X-Tonight-Update": "1", "Origin": "https://example.com"},
    {"X-Tonight-Update": "1", "Origin": "http://localhost:9999"}])
def test_foreign_site_cannot_trigger_update(manager, headers):
    with TestClient(main.app) as client:
        assert client.post("/api/updates/install", headers=headers).status_code == 403


def test_download_is_started_only_from_the_checked_offer(manager, monkeypatch):
    calls=[]
    async def job(update): calls.append(update.version)
    monkeypatch.setattr(main, "_download_and_install", job)
    with TestClient(main.app) as client:
        client.post("/api/updates/check", headers={"X-Tonight-Update": "1"})
        response=client.post("/api/updates/install", headers={"X-Tonight-Update": "1"})
        assert response.status_code == 202
        assert response.json()["phase"] == "downloading"
    assert calls == ["1.6.5"]


def test_external_hostname_cannot_rebind_to_localhost_for_update(manager):
    with TestClient(main.app, base_url="http://example.com") as client:
        response = client.post("/api/updates/install", headers={"X-Tonight-Update": "1", "Origin": "http://example.com"})
        assert response.status_code == 403


def test_invalid_package_at_handoff_keeps_tonight_running(manager, monkeypatch):
    import asyncio
    from pathlib import Path
    from backend.release import ReleaseError
    offer = auto.fetch_latest_update("1.6.4")
    monkeypatch.setattr(manager, "download_reserved", lambda update: Path("fixture.zip"))
    monkeypatch.setattr(main, "_update_shutdown", lambda: pytest.fail("Tonight must stay running"))
    def invalid(*args, **kwargs): raise ReleaseError("corrupt manifest")
    monkeypatch.setattr(main, "prepare_handoff", invalid)
    asyncio.run(main._download_and_install(offer))
    assert manager.status()["phase"] == "error"
