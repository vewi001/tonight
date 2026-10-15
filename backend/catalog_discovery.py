"""Pure catalog release selection, independent from application Latest."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import json
import re

import httpx

from backend.auto_update import AvailableUpdate, DIGEST, DOWNLOAD_PREFIX, HEADERS, UpdateError, _client
from backend.catalog_package import CatalogPackageError, _version, _date, _unique_object
from backend.release import MAX_RELEASE_BYTES

DELTA_MANIFEST_URL = 'https://raw.githubusercontent.com/vewi001/tonight/main/catalog/deltas.json'
MANIFEST_URL = 'https://raw.githubusercontent.com/vewi001/tonight/main/catalog/latest.json'
MAX_MANIFEST_BYTES = 16 * 1024


@dataclass(frozen=True)
class CatalogOffer(AvailableUpdate):
    min_app_version: str
    published_at: str
    base_version: str | None = None


def select_catalog_manifest(payload, current_catalog_version):
    fields = {'format_version','catalog_version','min_app_version','archive_url','size_bytes','sha256','published_at'}
    try:
        if not isinstance(payload,dict) or set(payload)!=fields or type(payload['format_version']) is not int or payload['format_version']!=1:
            raise ValueError
        version = _version(payload['catalog_version'])
        minimum = _version(payload['min_app_version'])
        published = _date(payload['published_at'])
        if len(published)>40: raise ValueError
        size,sha = payload['size_bytes'],payload['sha256']
        name = f'Tonight-catalog-{version}.zip'
        url = f'{DOWNLOAD_PREFIX}catalog-v{version}/{name}'
        if (payload['archive_url']!=url or type(size) is not int or not 0<size<=MAX_RELEASE_BYTES
                or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha)):
            raise ValueError
        if current_catalog_version is not None and _numbers(version)<=_numbers(current_catalog_version):
            return None
        return CatalogOffer(version,name,size,sha,url,minimum,published)
    except (ValueError,TypeError,KeyError):
        raise UpdateError('Не удалось проверить обновление. Попробуйте позже.') from None


def fetch_catalog_update(current_catalog_version: str | None, *, client: httpx.Client | None = None):
    """Manifest first. Only absent index (404) permits legacy API fallback."""
    try:
        with nullcontext(client) if client is not None else _client() as session:
            with session.stream('GET',MANIFEST_URL,headers={'User-Agent':'Tonight-updater','Accept-Encoding':'identity'},
                                follow_redirects=False) as response:
                if response.status_code!=404:
                    if response.status_code!=200:
                        raise UpdateError('Не удалось проверить обновление. Попробуйте позже.')
                    body = bytearray()
                    for chunk in response.iter_bytes(1024):
                        body.extend(chunk)
                        if len(body)>MAX_MANIFEST_BYTES:
                            raise UpdateError('Не удалось проверить обновление. Попробуйте позже.')
                    return select_catalog_manifest(json.loads(body,object_pairs_hook=_unique_object),current_catalog_version)
            return fetch_catalog_releases(current_catalog_version,client=session)
    except (httpx.HTTPError,ValueError):
        raise UpdateError('Не удалось проверить обновление. Попробуйте позже.') from None


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


def fetch_catalog_releases(current_catalog_version: str | None, *, client: httpx.Client | None = None) -> AvailableUpdate | None:
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


def validate_catalog_offer(update):
    """Validate both legacy full offers and version-pinned delta offers."""
    base = getattr(update, 'base_version', None)
    if base is None:
        if getattr(update, 'min_app_version', None) is not None:
            return select_catalog_manifest(dict(format_version=1, catalog_version=update.version,
                min_app_version=update.min_app_version, published_at=update.published_at,
                archive_url=update.url, size_bytes=update.size, sha256=update.sha256), None)
        return select_catalog_update([{'tag_name':'catalog-v'+update.version,'assets':[{
            'name':update.name,'size':update.size,'digest':'sha256:'+update.sha256,
            'browser_download_url':update.url}]}], None)
    base, version = _version(base), _version(update.version)
    name = f'Tonight-catalog-{base}-to-{version}.zip'
    expected = f'{DOWNLOAD_PREFIX}catalog-v{version}/{name}'
    if (_numbers(base) >= _numbers(version) or update.name != name or update.url != expected
            or type(update.size) is not int or not 0 < update.size <= MAX_RELEASE_BYTES
            or not isinstance(update.sha256,str) or not re.fullmatch('[a-f0-9]{64}', update.sha256)
            or _numbers(update.min_app_version) < (1,8,0)):
        raise UpdateError('Пакет изменений каталога не прошёл проверку.')
    _date(update.published_at)
    return update


def select_catalog_delta(payload, full, current):
    if not isinstance(payload,dict) or set(payload) != {'format_version','deltas'} or type(payload['format_version']) is not int or payload['format_version'] != 1 or not isinstance(payload['deltas'],list) or len(payload['deltas']) > 100:
        raise UpdateError('Некорректный список пакетов изменений каталога.')
    candidates, seen = [], set()
    for item in payload['deltas']:
        fields = {'base_version','catalog_version','min_app_version','published_at','archive_url','size_bytes','sha256'}
        if not isinstance(item,dict) or set(item) != fields:
            raise UpdateError('Некорректное описание пакета изменений каталога.')
        offer = CatalogOffer(item['catalog_version'], f"Tonight-catalog-{item['base_version']}-to-{item['catalog_version']}.zip",
                             item['size_bytes'], item['sha256'], item['archive_url'], item['min_app_version'], item['published_at'], item['base_version'])
        validate_catalog_offer(offer)
        key = (offer.base_version, offer.version)
        if key in seen:
            raise UpdateError('Пакет изменений каталога повторяется.')
        seen.add(key)
        if current is not None and offer.base_version == current and offer.version == full.version and offer.size < full.size:
            candidates.append(offer)
    return candidates[0] if candidates else full


def fetch_catalog_delta(full, current, *, client=None):
    if full is None or current is None:
        return full
    # A missing or unavailable optional index keeps full delivery available.
    try:
        with nullcontext(client) if client is not None else _client() as session:
            with session.stream('GET', DELTA_MANIFEST_URL, headers={'User-Agent':'Tonight-updater'}, follow_redirects=False) as response:
                if response.status_code != 200:
                    return full
                body = bytearray()
                for chunk in response.iter_bytes(1024):
                    body.extend(chunk)
                    if len(body) > 64*1024:
                        raise UpdateError('Описание пакетов изменений слишком большое.')
        return select_catalog_delta(json.loads(body, object_pairs_hook=_unique_object), full, current)
    except httpx.HTTPError:
        return full
