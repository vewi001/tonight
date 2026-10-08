from __future__ import annotations

import asyncio

import pytest

from backend.ollama import client


CANDIDATES = [
    {"id":"a","title":"A","year":2020,"runtime":100,"genres":["драма"],"rating":8.0,"overview":"x","score":.8,"match":90,"explanation_lera":"x","explanation_nikita":"x","compromise":"x"},
    {"id":"b","title":"B","year":2021,"runtime":90,"genres":["комедия"],"rating":7.5,"overview":"y","score":.7,"match":85,"explanation_lera":"y","explanation_nikita":"y","compromise":"y"},
]


def test_candidate_validation_rejects_hallucinated_id():
    raw = {"candidates":[{"id":"invented","explanation_lera":"x","explanation_nikita":"x","compromise":"x"}]}
    with pytest.raises(ValueError): client.apply_validated_rerank(CANDIDATES, raw)


def test_invalid_ollama_json_falls_back(monkeypatch):
    async def healthy(): return {"available":True,"model_installed":True}
    def malformed(*args, **kwargs): return {"response":"not-json"}
    monkeypatch.setattr(client, "health", healthy)
    monkeypatch.setattr(client, "_request", malformed)
    result = asyncio.run(client.rerank(CANDIDATES, {}))
    assert result == CANDIDATES

