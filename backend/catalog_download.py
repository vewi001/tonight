"""Resumable catalog download; only a fully verified ZIP can be installed."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import re
import time
from typing import Callable
from urllib.parse import urljoin

import httpx

from backend.auto_update import AvailableUpdate, DOWNLOAD_PREFIX, UpdateError, _client, _download_url_allowed
from backend.catalog_package import CatalogCompatibilityError, CatalogPackageError, _version, read_catalog_package
from backend.release import MAX_RELEASE_BYTES, _is_link

ATTEMPTS = 3
TRANSIENT = {408,429,500,502,503,504}


class CatalogCompatibilityUpdateError(UpdateError):
    def __init__(self, minimum: str):
        self.minimum = _version(minimum)
        super().__init__('Сначала обновите приложение Tonight.')


class CatalogIntegrityUpdateError(UpdateError):
    """Integrity failure; fixed safe UI advice, never arbitrary exception text."""


class CatalogDownloadInterrupted(UpdateError):
    def __init__(self, received, total):
        self.received,self.total = received,total
        super().__init__('Загрузка прервалась. Можно продолжить.')


def _validate(update, app_version):
    version = _version(update.version)
    app = _version(app_version)
    name = f'Tonight-catalog-{version}.zip'
    if (update.name!=name or update.url!=f'{DOWNLOAD_PREFIX}catalog-v{version}/{name}'
            or type(update.size) is not int or not 0<update.size<=MAX_RELEASE_BYTES
            or not isinstance(update.sha256,str) or not re.fullmatch('[a-f0-9]{64}',update.sha256)):
        raise UpdateError('Описание файла каталога не прошло проверку.')
    minimum = getattr(update,'min_app_version',None)
    if minimum is not None and tuple(map(int,app.split('.')))<tuple(map(int,_version(minimum).split('.'))):
        raise CatalogCompatibilityUpdateError(minimum)
    return version


def _verify(path, update, app_version):
    if path.stat().st_size!=update.size:
        raise CatalogIntegrityUpdateError('Размер каталога не совпал.')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk:=source.read(1024*1024): digest.update(chunk)
    if digest.hexdigest()!=update.sha256:
        raise CatalogIntegrityUpdateError('Каталог не прошёл проверку.')
    package = read_catalog_package(path,app_version=app_version)
    if package.version!=update.version or (getattr(update,'min_app_version',None) is not None
                                          and package.min_app_version!=update.min_app_version):
        raise CatalogIntegrityUpdateError('Описание пакета не совпало с манифестом.')


def _transfer(session, update, partial, progress):
    # Every retry starts at stable origin, not an expired signed CDN URL.
    offset = partial.stat().st_size
    url = update.url
    headers = {'User-Agent':'Tonight-updater','Accept-Encoding':'identity'}
    if offset: headers['Range'] = f'bytes={offset}-'
    for _ in range(6):
        if not _download_url_allowed(url):
            raise CatalogIntegrityUpdateError('Неожиданный адрес загрузки.')
        with session.stream('GET',url,headers=headers,follow_redirects=False) as response:
            if response.status_code in {301,302,303,307,308}:
                location = response.headers.get('location')
                if not location: raise CatalogIntegrityUpdateError('Нет адреса загрузки.')
                url = urljoin(url,location)
                continue
            if response.status_code in TRANSIENT:
                raise httpx.ReadError('Temporary catalog response')
            if response.status_code not in {200,206}:
                response.raise_for_status()
                raise CatalogIntegrityUpdateError('Неправильный ответ сервера.')
            if response.headers.get('content-encoding','identity').lower()!='identity':
                raise CatalogIntegrityUpdateError('Неправильное кодирование загрузки.')
            if response.status_code==206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('content-range',''))
                if (not offset or match is None or tuple(map(int,match.groups()))!=(offset,update.size-1,update.size)):
                    raise CatalogIntegrityUpdateError('Неправильное продолжение загрузки.')
                mode,total = 'ab',offset
            else:
                mode,total = 'wb',0
            expected = update.size-total
            length = response.headers.get('content-length')
            if length is not None and (not length.isascii() or not length.isdigit() or int(length)!=expected):
                raise CatalogIntegrityUpdateError('Размер ответа не совпал.')
            with partial.open(mode) as output:
                if progress: progress(total,update.size)
                try:
                    # No chunk-size buffering: retain last bytes before disconnect.
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total>update.size: raise CatalogIntegrityUpdateError('Размер каталога не совпал.')
                        output.write(chunk)
                        if progress: progress(total,update.size)
                finally:
                    output.flush()
                    os.fsync(output.fileno())
            if total!=update.size: raise httpx.ReadError('Incomplete catalog response')
            return
    raise CatalogIntegrityUpdateError('Слишком много переходов загрузки.')


def download_catalog(update: AvailableUpdate, destination: Path, *, app_version: str,
                     client: httpx.Client | None = None,
                     progress: Callable[[int,int],None] | None = None) -> Path:
    """Caller holds shared lease. Partial is bound to trusted content identity.

    Range bytes are untrusted until pinned full SHA/ZIP verification. We do
    not rely on ETag for integrity. Network failures retain partials on disk.
    """
    partial = None
    retain = False
    try:
        _validate(update,app_version)
        if any(_is_link(path) for path in (destination,*destination.parents)):
            raise UpdateError('Папка загрузки каталога не может быть ссылкой.')
        destination.mkdir(parents=True,exist_ok=True)
        target = destination/update.name
        partial = destination/(update.sha256+'.part')
        if (target.is_file() and partial.is_file() and not _is_link(target) and not _is_link(partial)
                and target.stat().st_nlink==2 and partial.stat().st_nlink==2 and target.samefile(partial)):
            # Recover a crash after publication but before unlinking our partial.
            _verify(target,update,app_version)
            partial.unlink()
            partial = None
            if progress: progress(update.size,update.size)
            return target
        for path in (target,partial):
            if _is_link(path) or (path.exists() and (not path.is_file() or path.stat().st_nlink!=1)):
                partial = None
                raise UpdateError('Небезопасный файл загрузки.')
        if target.exists():
            partial = None
            _verify(target,update,app_version)
            if progress: progress(update.size,update.size)
            return target
        if not partial.exists():
            with partial.open('xb'): pass
        if partial.stat().st_size>update.size:
            raise CatalogIntegrityUpdateError('Размер каталога не совпал.')
        if progress: progress(partial.stat().st_size,update.size)
        with nullcontext(client) if client is not None else _client() as session:
            for attempt in range(ATTEMPTS):
                if partial.stat().st_size==update.size: break
                try:
                    _transfer(session,update,partial,progress)
                    break
                except httpx.TransportError:
                    if attempt==ATTEMPTS-1:
                        retain = True
                        raise CatalogDownloadInterrupted(partial.stat().st_size,update.size) from None
                    time.sleep(attempt+1)
        _verify(partial,update,app_version)
        os.link(partial,target)
        return target
    except CatalogCompatibilityError as error:
        raise CatalogCompatibilityUpdateError(error.minimum) from None
    except CatalogPackageError:
        raise CatalogIntegrityUpdateError('Каталог повреждён или несовместим.') from None
    except (httpx.HTTPError,OSError,ValueError) as error:
        if isinstance(error,UpdateError): raise
        raise UpdateError('Не удалось скачать каталог. Попробуйте позже.') from None
    finally:
        if partial is not None and not retain:
            partial.unlink(missing_ok=True)
