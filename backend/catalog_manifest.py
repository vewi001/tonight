"""Prepare public delivery metadata from a verified ZIP; never publish."""
import hashlib
import json
from pathlib import Path

from backend.auto_update import DOWNLOAD_PREFIX
from backend.catalog_package import read_catalog_package, _date
from backend.catalog_discovery import select_catalog_manifest
from backend.release import _is_link


def build_catalog_manifest(archive: Path, destination: Path, *, published_at: str):
    published_at = _date(published_at)
    if any(_is_link(p) for p in (archive,*archive.parents,destination,*destination.parents)):
        raise ValueError('Manifest paths cannot be links')
    package = read_catalog_package(archive)
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source,'sha256').hexdigest()
    name = f'Tonight-catalog-{package.version}.zip'
    payload = dict(format_version=1,catalog_version=package.version,min_app_version=package.min_app_version,
                   archive_url=f'{DOWNLOAD_PREFIX}catalog-v{package.version}/{name}',
                   size_bytes=archive.stat().st_size,sha256=digest,published_at=published_at)
    select_catalog_manifest(payload,None)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    return destination
