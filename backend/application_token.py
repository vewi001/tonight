"""Load the owner-authorized application credential from the release assets."""
import json
from pathlib import Path


def application_token(assets: Path) -> str:
    path = assets / 'app-tmdb.json'
    try:
        if path.stat().st_size > 4096:
            return ''
        value = json.loads(path.read_text(encoding='utf-8')).get('token')
        return value.strip() if isinstance(value, str) else ''
    except (OSError, ValueError, AttributeError):
        return ''
