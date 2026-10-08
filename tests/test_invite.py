from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.network import invite_url


def test_invite_url_uses_lan_address_and_active_port():
    assert invite_url("192.168.1.42", 8011) == "http://192.168.1.42:8011/?join=1"


def test_invite_api_exposes_current_evening_and_qr(monkeypatch):
    monkeypatch.setenv("TONIGHT_ACTIVE_PORT", "8011")
    monkeypatch.setattr("backend.main.lan_ip", lambda: "192.168.1.42")
    client = TestClient(app)

    payload = client.get("/api/invite").json()
    qr = client.get("/api/invite/qr.svg")

    assert payload["url"] == "http://192.168.1.42:8011/?join=1"
    assert payload["display_url"] == "192.168.1.42:8011"
    assert payload["session"]["id"]
    assert qr.status_code == 200
    assert qr.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in qr.content


def test_frontend_keeps_technical_setup_details_collapsed():
    source = (app_dir() / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "Каталог готов" in source
    assert "Постеры загружены" in source
    assert "Можно выбирать фильм" in source
    assert "Если что-то не работает" in source
    assert "Открой камерой телефона" in source
    assert "Код вечера" in source
    assert "Введите код с экрана" in source
    assert 'data-action="copy-invite"' in source


def app_dir():
    from backend.config import ROOT

    return ROOT
