from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from pydantic import ValidationError

from backend.config import settings
from backend.models.schemas import OllamaResponse


def _request(path: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{settings.ollama_url}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout or settings.ollama_timeout) as response:
        return json.loads(response.read().decode("utf-8"))


async def health() -> dict[str, Any]:
    try:
        data = await asyncio.to_thread(_request, "/api/tags", None, 2.5)
        names = [item.get("name", "") for item in data.get("models", [])]
        desired = settings.ollama_model
        installed = desired in names or any(name.split(":")[0] == desired.split(":")[0] for name in names)
        return {"available": True, "model": desired, "model_installed": installed, "models": names}
    except Exception as exc:
        return {"available": False, "model": settings.ollama_model, "model_installed": False, "error": type(exc).__name__}


def apply_validated_rerank(candidates: list[dict[str, Any]], raw: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = OllamaResponse.model_validate(raw)
    by_id = {item["id"]: item for item in candidates}
    incoming_ids = [item.id for item in parsed.candidates]
    if not incoming_ids or any(movie_id not in by_id for movie_id in incoming_ids):
        raise ValueError("Ollama returned an unknown movie id")
    result: list[dict[str, Any]] = []
    for explanation in parsed.candidates:
        movie = dict(by_id[explanation.id])
        movie["explanation_lera"] = explanation.explanation_lera
        movie["explanation_nikita"] = explanation.explanation_nikita
        movie["compromise"] = explanation.compromise
        result.append(movie)
    result.extend(dict(movie) for movie in candidates if movie["id"] not in incoming_ids)
    return result


async def rerank(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> list[dict[str, Any]]:
    status = await health()
    if not status["available"] or not status["model_installed"]:
        return candidates
    facts = [
        {"id": m["id"], "title": m["title"], "year": m["year"], "runtime": m["runtime"], "genres": m["genres"], "rating": m["rating"], "overview": m["overview"], "deterministic_score": m["score"]}
        for m in candidates
    ]
    prompt = (
        "Ты помогаешь паре выбрать фильм. Используй ТОЛЬКО переданные ID и факты. "
        "Не добавляй фильмы, не меняй метаданные. Переставь кандидатов только если это улучшает общий компромисс. "
        "Верни JSON по схеме. Объяснения на русском, без выдуманных сюжетных фактов, каждое не длиннее двух предложений.\n"
        f"Предпочтения: {json.dumps(preferences, ensure_ascii=False)}\n"
        f"Кандидаты: {json.dumps(facts, ensure_ascii=False)}"
    )
    payload = {
        "model": settings.ollama_model, "prompt": prompt, "stream": False,
        "format": OllamaResponse.model_json_schema(), "options": {"temperature": 0.15},
    }
    try:
        response = await asyncio.to_thread(_request, "/api/generate", payload, settings.ollama_timeout)
        content = response.get("response", "")
        raw = json.loads(content)
        return apply_validated_rerank(candidates, raw)
    except Exception:
        # Reranking is optional. No local-model issue may block a valid
        # deterministic recommendation from reaching the two browsers.
        return candidates

