from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_diagnostics_returns_simple_checks_and_a_sanitized_log():
    client = TestClient(app)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload["checks"]} == {"database", "catalog", "network", "images", "ollama"}
    assert payload["summary"]["text"] in {"Всё готово", "Нужно проверить подключение к домашней сети"}
    assert "token" not in payload["technical_log"].lower()
    assert "history" not in payload["technical_log"].lower()


def test_frontend_keeps_diagnostics_simple_and_log_separate():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Проверить приложение" in source
    assert "Технический журнал" in source
    assert 'data-action="copy-diagnostics"' in source
