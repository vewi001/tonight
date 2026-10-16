"""Load Tonight's owner-authorized public key in source and packaged installs."""
import json
from pathlib import Path


def application_token(assets: Path) -> str:
    # Packaged/env-specific build credentials retain precedence over the public default.
    for path in (assets / 'app-tmdb.json', assets / 'app' / 'tmdb-public.json'):
        try:
            if path.stat().st_size > 4096:
                continue
            value = json.loads(path.read_text(encoding='utf-8')).get('token')
            if isinstance(value, str) and value.strip():
                return value.strip()
        except (OSError, ValueError, AttributeError):
            continue
    return ''
