from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.runtime_paths import resolve_runtime_paths


_paths = resolve_runtime_paths(
    Path(__file__),
    frozen=bool(getattr(sys, "frozen", False)),
    executable=Path(sys.executable),
    bundle_dir=Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])),
)
ROOT = _paths.root
ASSET_ROOT = _paths.assets


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("TONIGHT_HOST", "0.0.0.0")
    port: int = int(os.getenv("TONIGHT_PORT", "8000"))
    db_path: Path = ROOT / os.getenv("TONIGHT_DB", "data/tonight.db")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "18"))
    # A previous .env may still contain the old value 8 or 12. Never give a
    # couple fewer than twenty cards, while allowing a larger personal value.
    swipe_count: int = max(20, int(os.getenv("TONIGHT_SWIPE_COUNT", "20")))
    candidate_count: int = int(os.getenv("TONIGHT_CANDIDATE_COUNT", "7"))
    tmdb_read_token: str = os.getenv("TMDB_READ_TOKEN", "")
    catalog_auto_update: bool = _env_flag("CATALOG_AUTO_UPDATE", bool(os.getenv("TMDB_READ_TOKEN")))
    catalog_refresh_days: int = int(os.getenv("CATALOG_REFRESH_DAYS", "7"))
    catalog_pages: int = int(os.getenv("CATALOG_PAGES", "25"))
    catalog_list: str = os.getenv("CATALOG_LIST", "smart")  # kept for old .env compatibility
    catalog_min_votes: int = max(1, int(os.getenv("CATALOG_MIN_VOTES", "50")))
    catalog_images: bool = _env_flag("CATALOG_IMAGES", False)


settings = Settings()


SCORING = {
    "average_weight": 0.38,
    "minimum_weight": 0.42,
    "pair_history_weight": 0.12,
    "catalog_weight": 0.08,
    "disagreement_penalty": 0.34,
    "strong_dislike_penalty": 0.42,
    "vibe_match": 0.13,
    "genre_signal": 0.16,
    "energy_mismatch": 0.12,
}
