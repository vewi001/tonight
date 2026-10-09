"""Verified catalog ZIP download; never install an incomplete or incompatible file."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Callable
from urllib.parse import urljoin

import httpx

from backend.auto_update import AvailableUpdate, DOWNLOAD_PREFIX, UpdateError, _client, _download_url_allowed
from backend.catalog_package import CatalogCompatibilityError, CatalogPackageError, _version, read_catalog_package
from backend.release import MAX_RELEASE_BYTES, _is_link


class CatalogCompatibilityUpdateError(UpdateError):
    def __init__(self, minimum: str):
        self.minimum = _version(minimum)
        super().__init__('Сначала обновите приложение Tonight.')


class CatalogIntegrityUpdateError(UpdateError):
    """A failed size/hash check; public UI must not forward exception text."""


def download_catalog(update: AvailableUpdate, destination: Path, *, app_version: str,
                     client: httpx.Client | None = None,
                     progress: Callable[[int,int],None] | None = None) -> Path:
    """Return a fully verified ZIP, not an installation or a success marker.

    Caller provides its private update staging directory and owns the job lock.
    Output is published without overwrite; any existing file is preserved.
    Production requests use the app updater's credential-free HTTP client.
    """
    partial = None
    try:
        version = _version(update.version)
        _version(app_version)
        name = f'Tonight-catalog-{version}.zip'
        if (update.name!=name or update.url!=f'{DOWNLOAD_PREFIX}catalog-v{version}/{name}'
                or type(update.size) is not int or not 0<update.size<=MAX_RELEASE_BYTES
                or not isinstance(update.sha256,str) or not re.fullmatch('[a-f0-9]{64}',update.sha256)):
            raise UpdateError('Описание файла каталога не прошло проверку.')
        if any(_is_link(path) for path in (destination,*destination.parents)):
            raise UpdateError('Папка загрузки каталога не может быть ссылкой.')
        destination.mkdir(parents=True,exist_ok=True)
        target = destination/name
        if target.exists() or target.is_symlink():
            raise UpdateError('Файл с таким именем уже существует. Повторите загрузку в новую папку.')
        handle,temporary = tempfile.mkstemp(prefix='.catalog-download-',suffix='.part',dir=destination)
        partial = Path(temporary)
        with os.fdopen(handle,'wb') as output:
            with nullcontext(client) if client is not None else _client() as session:
                url = update.url
                for _ in range(6):
                    if not _download_url_allowed(url):
                        raise UpdateError('GitHub направил каталог по неожиданному адресу.')
                    with session.stream('GET',url,headers={'User-Agent':'Tonight-updater','Accept-Encoding':'identity'},
                                        follow_redirects=False) as response:
                        if response.status_code in {301,302,303,307,308}:
                            location = response.headers.get('location')
                            if not location:
                                raise UpdateError('GitHub не указал адрес загрузки каталога.')
                            url = urljoin(url,location)
                            continue
                        response.raise_for_status()
                        total,digest = 0,hashlib.sha256()
                        for chunk in response.iter_bytes(64*1024):
                            total += len(chunk)
                            if total>update.size:
                                raise CatalogIntegrityUpdateError('Размер скачанного каталога не совпал. Попробуйте снова.')
                            digest.update(chunk)
                            output.write(chunk)
                            if progress:
                                progress(total,update.size)
                        if total!=update.size or digest.hexdigest()!=update.sha256:
                            raise CatalogIntegrityUpdateError('Каталог не прошёл проверку контрольной суммы. Попробуйте снова.')
                        break
                else:
                    raise UpdateError('Не удалось найти файл каталога на GitHub.')
        package = read_catalog_package(partial,app_version=app_version)
        if package.version!=version:
            raise UpdateError('Версия внутри пакета каталога не совпадает с релизом.')
        os.link(partial,target)
        return target
    except CatalogCompatibilityError as error:
        raise CatalogCompatibilityUpdateError(error.minimum) from None
    except CatalogPackageError:
        raise UpdateError('Каталог повреждён или несовместим. Проверьте обновление Tonight.') from None
    except (httpx.HTTPError,OSError,ValueError) as exc:
        if isinstance(exc,UpdateError):
            raise
        raise UpdateError('Не удалось скачать каталог. Локальный выбор фильмов продолжит работать.') from None
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
