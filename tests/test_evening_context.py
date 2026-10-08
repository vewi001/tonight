from __future__ import annotations

from backend.config import ROOT


def test_quick_evening_offers_five_plain_contexts_and_preserves_stop_genres():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    for label in (
        "Устали",
        "Поздно, нужен короткий фильм",
        "Хотим что-то лёгкое",
        "Готовы внимательно смотреть",
        "Можно рискнуть и удивиться",
    ):
        assert label in source

    assert "Стоп-жанры на сегодня" in source
    assert "disliked_genres:[...state.prefs.disliked_genres]" in source
    assert "disliked_genres:[]" not in source[source.index("async function startQuickEvening"):source.index("function renderVibe")]
