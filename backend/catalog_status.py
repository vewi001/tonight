"""Read-only catalog summary. File/link presence is not video availability."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from backend.catalog_package import CatalogPackageError, EXTENSIONS, IDENTIFIER, _date, _version
from backend.movies.trailers import YOUTUBE_KEY
from backend.release import ReleaseError, _is_link, _safe_relative


def _posters(data_dir: Path) -> set[str]:
    directory = data_dir/'posters'
    result = set()
    try:
        if any(_is_link(path) for path in (directory,data_dir,*data_dir.parents)):
            return result
        for path in directory.iterdir():
            if path.suffix.lower() not in EXTENSIONS or not IDENTIFIER.fullmatch(path.stem):
                continue
            try:
                _safe_relative(path.name)
                if not _is_link(path) and path.is_file() and path.stat().st_size>0:
                    result.add(path.stem.casefold())
            except (OSError,ReleaseError):
                continue
    except OSError:
        pass  # An unavailable cache must not block the local catalog.
    return result


def get_catalog_summary(db: sqlite3.Connection, data_dir: Path) -> dict:
    """No writes/network calls; no private values or filesystem paths returned.

    Counts nonempty ordinary local poster files, not decoded image validity.
    Trailer counts mean syntactically valid YouTube links, not working videos.
    Future installer writes catalog_version/catalog_updated_at only on commit.
    """
    posters = _posters(data_dir)
    counts = dict(movie_count=0,local_poster_count=0,trailer_link_count=0,poster_and_trailer_count=0)
    for identifier,trailer_key in db.execute('SELECT id,trailer_key FROM movies'):
        poster = identifier.casefold() in posters
        trailer = isinstance(trailer_key,str) and YOUTUBE_KEY.fullmatch(trailer_key) is not None
        counts['movie_count'] += 1
        counts['local_poster_count'] += int(poster)
        counts['trailer_link_count'] += int(trailer)
        counts['poster_and_trailer_count'] += int(poster and trailer)
    meta = dict(db.execute("SELECT key,value FROM app_meta WHERE key IN ('catalog_version','catalog_updated_at')"))
    for key,validator in (('catalog_version',_version),('catalog_updated_at',_date)):
        try:
            meta[key] = validator(meta.get(key))
        except CatalogPackageError:
            meta[key] = None
    return dict(counts,catalog_version=meta['catalog_version'],last_successful_update=meta['catalog_updated_at'])
