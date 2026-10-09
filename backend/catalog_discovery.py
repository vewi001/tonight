"""Pure catalog release selection, independent from application Latest."""
from __future__ import annotations

from contextlib import nullcontext

import httpx

from backend.auto_update import AvailableUpdate, DIGEST, DOWNLOAD_PREFIX, HEADERS, UpdateError, _client
from backend.catalog_package import CatalogPackageError, _version
from backend.release import MAX_RELEASE_BYTES


def _numbers(version: str) -> tuple[int,...]:
    return tuple(map(int,_version(version).split('.')))


def select_catalog_update(releases: list, current_catalog_version: str | None) -> AvailableUpdate | None:
    """Select a public catalog candidate; compatibility is checked after download.

    Caller must collect release-list pages (not application /latest). No network
    or writes here. Exact repo/tag/asset URL and GitHub digest are mandatory.
    Current None means an unversioned legacy installation, not app version.
    """
    try:
        current = _numbers(current_catalog_version) if current_catalog_version is not None else None
    except CatalogPackageError:
        raise UpdateError('Не удалось определить установленную версию каталога.') from None
    if not isinstance(releases,list):
        raise UpdateError('GitHub вернул непонятный список каталогов. Попробуйте позже.')
    candidates = []
    for release in releases:
        if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):
            continue
        tag = release.get('tag_name')
        if not isinstance(tag,str) or not tag.startswith('catalog-v'):
            continue
        version = tag[len('catalog-v'):]
        try:
            numbers = _numbers(version)
        except CatalogPackageError:
            continue
        if current is not None and numbers<=current:
            continue
        assets = release.get('assets')
        if not isinstance(assets,list):
            raise UpdateError('Не удалось прочитать файлы каталога в релизе.')
        name = f'Tonight-catalog-{version}.zip'
        selected = [asset for asset in assets if isinstance(asset,dict) and asset.get('name')==name]
        if selected:
            candidates.append((numbers,version,selected))
    if not candidates:
        return None
    newest = max(item[0] for item in candidates)
    selected_releases = [item for item in candidates if item[0]==newest]
    if len(selected_releases)!=1 or len(selected_releases[0][2])!=1:
        raise UpdateError('В релизах повторяется версия или файл каталога.')
    _,version,assets = selected_releases[0]
    asset = assets[0]
    name = f'Tonight-catalog-{version}.zip'
    expected_url = f'{DOWNLOAD_PREFIX}catalog-v{version}/{name}'
    size = asset.get('size')
    digest = DIGEST.fullmatch(str(asset.get('digest','')))
    if type(size) is not int or not 0<size<=MAX_RELEASE_BYTES:
        raise UpdateError('Размер каталога не подходит для Tonight.')
    if digest is None:
        raise UpdateError('В релизе нет контрольной суммы каталога. Попробуйте позже.')
    if asset.get('browser_download_url')!=expected_url:
        raise UpdateError('Файл каталога находится по неожиданному адресу.')
    return AvailableUpdate(version,name,size,digest[1].lower(),expected_url)


def fetch_catalog_update(current_catalog_version: str | None, *, client: httpx.Client | None = None) -> AvailableUpdate | None:
    """Public paginated list; bounded exhaustion is an error, not current.

    Production uses trust_env=False, no authorization or TMDB token. Future
    manager owns check throttling/cache; this function never installs.
    """
    try:
        releases = []
        with nullcontext(client) if client is not None else _client() as session:
            for page in range(1,11):
                response = session.get(f'https://api.github.com/repos/vewi001/tonight/releases?per_page=100&page={page}',
                                       headers=HEADERS)
                if response.status_code==404 and page==1:
                    return None
                if response.status_code in {403,429}:
                    raise UpdateError('GitHub просит подождать. Проверьте каталог позже.')
                response.raise_for_status()
                values = response.json()
                if not isinstance(values,list) or len(values)>100:
                    raise UpdateError('GitHub вернул непонятный список каталогов.')
                releases.extend(values)
                if len(values)<100:
                    return select_catalog_update(releases,current_catalog_version)
        raise UpdateError('Список релизов слишком большой для полной проверки каталога. Попробуйте позже.')
    except (httpx.HTTPError,ValueError) as exc:
        if isinstance(exc,UpdateError):
            raise
        raise UpdateError('Не удалось проверить каталог. Можно продолжать вечер и попробовать позже.') from None
