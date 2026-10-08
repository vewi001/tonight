from __future__ import annotations

import re

ALIASES = {
    "science fiction": "sci-fi", "science-fiction": "sci-fi", "sci fi": "sci-fi",
    "sci-fi": "sci-fi", "scifi": "sci-fi", "sf": "sci-fi",
    "фантастика": "sci-fi", "научная фантастика": "sci-fi",
    "horror": "хоррор", "ужас": "хоррор", "ужасы": "хоррор", "хоррор": "хоррор",
    "romance": "романтика", "мелодрама": "романтика", "романтический": "романтика",
    "animation": "мультфильм", "анимация": "мультфильм",
    "documentary": "документальное", "документальный": "документальное",
    "action": "боевик", "adventure": "приключения", "comedy": "комедия",
    "crime": "криминал", "drama": "драма", "family": "семейный",
    "fantasy": "фэнтези", "history": "история", "music": "музыка",
    "mystery": "детектив", "thriller": "триллер", "war": "военный",
    "western": "вестерн",
}


def canonical_genre(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower().replace("‑", "-").replace("–", "-"))
    return ALIASES.get(normalized, normalized)


def normalize_genres(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        genre = canonical_genre(value)
        if genre and genre not in result:
            result.append(genre)
    return result

