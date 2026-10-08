from __future__ import annotations

import re
from typing import Any


YOUTUBE_KEY = re.compile(r"^[A-Za-z0-9_-]{11}$")


def trailer_url(key: str | None) -> str | None:
    if not key or not YOUTUBE_KEY.fullmatch(key):
        return None
    return f"https://www.youtube.com/watch?v={key}"


def _valid_video(item: dict[str, Any]) -> bool:
    return (
        item.get("site") == "YouTube"
        and bool(YOUTUBE_KEY.fullmatch(str(item.get("key") or "")))
        and item.get("type") in {"Trailer", "Teaser"}
    )


def select_youtube_trailer(
    russian_videos: list[dict[str, Any]],
    english_videos: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Apply Tonight's documented language/official trailer priority."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*russian_videos, *english_videos]:
        key = str(item.get("key") or "")
        if key in seen or not _valid_video(item):
            continue
        seen.add(key)
        candidates.append(item)

    priorities = (
        lambda item: item.get("iso_639_1") == "ru" and item.get("type") == "Trailer",
        lambda item: item.get("iso_639_1") == "en" and item.get("type") == "Trailer" and bool(item.get("official")),
        lambda item: item.get("type") == "Trailer" and bool(item.get("official")),
        lambda item: item.get("type") == "Trailer",
        lambda item: bool(item.get("official")),
        lambda item: True,
    )
    for predicate in priorities:
        match = next((item for item in candidates if predicate(item)), None)
        if match:
            return {"key": str(match["key"]), "language": str(match.get("iso_639_1") or "und")}
    return None
