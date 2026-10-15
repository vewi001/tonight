"""Build a delta exclusively from two validated public catalog archives."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

from backend.catalog_package import MANIFEST, CatalogPackageError, read_catalog_package


def build_catalog_delta(base: Path, target: Path, output: Path) -> Path:
    before, after = read_catalog_package(base), read_catalog_package(target)
    if before.base_version or after.base_version or tuple(map(int, before.version.split('.'))) >= tuple(map(int, after.version.split('.'))):
        raise CatalogPackageError('Нужны два полных каталога с возрастающими версиями')
    if output.exists() or output.is_symlink():
        raise CatalogPackageError('Выходной архив уже существует')
    old_movies = {m['id']: m for m in before.movies}
    # Existing pictures are user-owned and preserved by the installer. Transfer
    # only additions, including a movie row for every added image's identifier.
    additions = set(after.media_files) - set(before.media_files)
    required_ids = {Path(name).stem for name in additions}
    movies = [m for m in after.movies if old_movies.get(m['id']) != m or m['id'] in required_ids]
    if not movies:
        raise CatalogPackageError('В каталогах нет изменений для отдельного пакета')
    payload = json.dumps(movies, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    with zipfile.ZipFile(target) as source:
        target_manifest = json.loads(source.read(MANIFEST))
        files = {name: target_manifest['files'][name] for name in sorted(additions)}
        files['movies.json'] = {'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        manifest = dict(product='Tonight', kind='catalog', format=2, version=after.version,
                        base_version=before.version, min_app_version='1.8.0', created_at=after.created_at,
                        movie_count=len(movies), files=files)
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.zip')
        os.close(fd)
        temporary = Path(temporary)
        try:
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, sort_keys=True))
                archive.writestr('movies.json', payload)
                for name in sorted(additions):
                    archive.writestr(name, source.read(name))
            read_catalog_package(temporary, app_version='1.8.0')
            os.link(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return output


def delta_manifest(archive: Path, published_at: str) -> dict:
    from backend.auto_update import DOWNLOAD_PREFIX
    from backend.catalog_package import _date
    from backend.catalog_discovery import CatalogOffer, validate_catalog_offer
    package = read_catalog_package(archive)
    if not package.base_version:
        raise CatalogPackageError('Ожидается пакет изменений')
    name = f'Tonight-catalog-{package.base_version}-to-{package.version}.zip'
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    item = dict(base_version=package.base_version, catalog_version=package.version,
                min_app_version=package.min_app_version, published_at=_date(published_at),
                archive_url=f'{DOWNLOAD_PREFIX}catalog-v{package.version}/{name}',
                size_bytes=archive.stat().st_size, sha256=digest)
    validate_catalog_offer(CatalogOffer(package.version, name, item['size_bytes'], digest, item['archive_url'],
                                      package.min_app_version, published_at, package.base_version))
    return item
