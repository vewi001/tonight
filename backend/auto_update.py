"""Public GitHub release discovery and verified, streamed update downloads."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import zipfile
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from typing import Callable

import httpx

from backend.release import MAX_RELEASE_BYTES, ReleaseError, read_release, _is_link
from backend.update_guard import acquire_update_lease, UpdateGuardError

LATEST_URL = "https://api.github.com/repos/vewi001/tonight/releases/latest"
APP_MANIFEST_URL = "https://raw.githubusercontent.com/vewi001/tonight/main/app/latest.json"
DOWNLOAD_PREFIX = "https://github.com/vewi001/tonight/releases/download/"
VERSION = re.compile(r"(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
DIGEST = re.compile(r"sha256:([a-fA-F0-9]{64})\Z")
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
           "User-Agent": "Tonight-updater"}
DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


class UpdateError(ValueError):
    """A public update cannot be checked, downloaded, or trusted."""


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    name: str
    size: int
    sha256: str
    url: str


def select_update(payload: dict, current_version: str) -> AvailableUpdate | None:
    """Accept only one stable, newer update asset belonging to Tonight."""
    if not isinstance(payload, dict):
        raise UpdateError("GitHub вернул непонятный ответ. Попробуйте позже.")
    match = VERSION.fullmatch(str(payload.get("tag_name", "")))
    current = VERSION.fullmatch(current_version)
    if not current:
        raise UpdateError("Не удалось определить текущую версию Tonight.")
    if payload.get("draft") or payload.get("prerelease") or not match:
        return None
    if tuple(map(int, match.groups())) <= tuple(map(int, current.groups())):
        return None
    version = ".".join(match.groups())
    name = f"Tonight-update-{version}.zip"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("В релизе не удалось прочитать список файлов.")
    selected = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
    if not selected:
        return None
    if len(selected) != 1:
        raise UpdateError("В релизе повторяется файл обновления.")
    asset = selected[0]
    size = asset.get("size")
    digest = DIGEST.fullmatch(str(asset.get("digest", "")))
    expected_url = f"{DOWNLOAD_PREFIX}v{version}/{name}"
    if type(size) is not int or not 0 < size <= MAX_RELEASE_BYTES:
        raise UpdateError("Размер обновления не подходит для Tonight.")
    if not digest:
        raise UpdateError("В релизе нет контрольной суммы. Обновление пока недоступно.")
    if asset.get("browser_download_url") != expected_url:
        raise UpdateError("Файл обновления находится по неожиданному адресу.")
    return AvailableUpdate(version, name, size, digest[1].lower(), expected_url)


def _client():
    # Do not inherit local proxy/auth environment or a TMDB client/session.
    return httpx.Client(timeout=httpx.Timeout(30, connect=10), trust_env=False, follow_redirects=False)


def select_app_manifest(payload: dict, current_version: str) -> AvailableUpdate | None:
    """Strict delivery metadata, with the same archive checks as Releases API."""
    fields={'format_version','app_version','archive_url','size_bytes','sha256'}
    if not isinstance(payload,dict) or set(payload)!=fields or type(payload.get('format_version')) is not int or payload['format_version']!=1:
        raise UpdateError('Описание обновления имеет неподдерживаемый формат.')
    version=payload['app_version']
    if not isinstance(version,str) or not VERSION.fullmatch(version) or version.startswith('v'):
        raise UpdateError('Не удалось определить версию обновления.')
    digest=payload['sha256']
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
        raise UpdateError('В описании обновления нет контрольной суммы.')
    # Validate unsafe metadata even when its version is not newer.
    metadata={'tag_name':version,'draft':False,'prerelease':False,'assets':[{
        'name':f'Tonight-update-{version}.zip','size':payload['size_bytes'],
        'digest':'sha256:'+digest,'browser_download_url':payload['archive_url']}]}
    validated=select_update(metadata,'0.0.0')
    if validated is None: raise UpdateError('Не удалось проверить описание обновления.')
    return select_update(metadata,current_version)


def _unique_manifest_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise UpdateError('В описании обновления повторяются поля.')
        result[key]=value
    return result


def fetch_latest_update(current_version: str, *, client: httpx.Client | None = None) -> AvailableUpdate | None:
    try:
        with nullcontext(client) if client is not None else _client() as session:
            with session.stream('GET',APP_MANIFEST_URL,headers={'Accept':'application/json','User-Agent':'Tonight-updater'}) as manifest:
                if manifest.status_code!=404:
                    manifest.raise_for_status()
                    data=bytearray()
                    for chunk in manifest.iter_bytes():
                        data.extend(chunk)
                        if len(data)>16*1024: raise UpdateError('Описание обновления слишком большое.')
                    return select_app_manifest(json.loads(data,object_pairs_hook=_unique_manifest_object),current_version)
            response = session.get(LATEST_URL, headers=HEADERS)
            if response.status_code == 404:
                return None
            if response.status_code in {403, 429}:
                raise UpdateError("GitHub просит подождать. Проверьте обновления позже.")
            response.raise_for_status()
            return select_update(response.json(), current_version)
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError("Не удалось проверить обновления. Можно продолжать вечер и попробовать позже.") from None


def _download_url_allowed(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in DOWNLOAD_HOSTS and
            parts.port in {None, 443} and not parts.username and not parts.password)


class UpdateDownloadInterrupted(UpdateError):
    def __init__(self, received: int, total: int):
        self.received, self.total = received, total
        super().__init__('Загрузка прервалась. Скачанная часть сохранена — можно продолжить.')


def _partial_update_bytes(update: AvailableUpdate | None, destination: Path) -> int:
    if update is None or not re.fullmatch('[a-f0-9]{64}', update.sha256):
        return 0
    path = destination / (update.sha256 + '.part')
    try:
        if any(_is_link(p) for p in (path, destination, *destination.parents)):
            return 0
        if path.is_file() and path.stat().st_nlink == 1:
            return min(path.stat().st_size, update.size)
    except OSError:
        pass
    return 0


def _verify_app_package(path: Path, update: AvailableUpdate) -> None:
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if path.stat().st_size != update.size or digest != update.sha256:
        raise UpdateError('Скачанный файл не прошёл проверку. Повторите загрузку.')
    release = read_release(path)
    if release.version != update.version or 'Tonight.exe' not in release.files:
        raise UpdateError('Содержимое пакета не соответствует версии Tonight.')
    with zipfile.ZipFile(path) as bundle:
        if bundle.testzip() is not None:
            raise UpdateError('Архив обновления повреждён. Повторите загрузку.')


def _transfer_app_update(session, update, partial, progress):
    # Start every attempt at the stable release URL, not an expired CDN link.
    offset = partial.stat().st_size
    url = update.url
    headers = {'User-Agent': 'Tonight-updater', 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    for _ in range(6):
        if not _download_url_allowed(url):
            raise UpdateError('GitHub направил загрузку по неожиданному адресу.')
        with session.stream('GET', url, headers=headers, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get('location')
                if not location:
                    raise UpdateError('GitHub не указал адрес загрузки.')
                url = urljoin(url, location)
                continue
            if response.status_code in {408, 429, 500, 502, 503, 504}:
                raise httpx.ReadError('Temporary app download response')
            response.raise_for_status()
            if response.status_code not in {200, 206} or response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise UpdateError('Неправильный ответ сервера обновлений.')
            if response.status_code == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('content-range', ''))
                if not offset or match is None or tuple(map(int, match.groups())) != (offset, update.size - 1, update.size):
                    raise UpdateError('Сервер вернул неправильное продолжение загрузки.')
                mode, total = 'ab', offset
            else:
                # A server may ignore Range. Restart instead of appending a full ZIP.
                mode, total = 'wb', 0
            length = response.headers.get('content-length')
            if length is not None and (not length.isascii() or not length.isdigit() or int(length) != update.size - total):
                raise UpdateError('Размер ответа не совпал с пакетом обновления.')
            with partial.open(mode) as output:
                if progress:
                    progress(total, update.size)
                try:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > update.size:
                            raise UpdateError('Размер скачанного обновления не совпал.')
                        output.write(chunk)
                        if progress:
                            progress(total, update.size)
                finally:
                    output.flush()
                    os.fsync(output.fileno())
            if total != update.size:
                raise httpx.ReadError('Incomplete app download')
            return
    raise UpdateError('Не удалось найти файл обновления на GitHub.')


def download_update(update: AvailableUpdate, destination: Path, *, client: httpx.Client | None = None,
                    progress: Callable[[int, int], None] | None = None) -> Path:
    """Retain interrupted transfers; publish only a fully verified app package."""
    partial, retain = None, False
    try:
        select_app_manifest({'format_version': 1, 'app_version': update.version, 'archive_url': update.url,
                             'size_bytes': update.size, 'sha256': update.sha256}, '0.0.0')
        if update.name != f'Tonight-update-{update.version}.zip':
            raise UpdateError('Неправильное имя пакета обновления.')
        if any(_is_link(path) for path in (destination, *destination.parents)):
            raise UpdateError('Папка обновлений не может быть ссылкой.')
        destination.mkdir(parents=True, exist_ok=True)
        target, candidate = destination / update.name, destination / (update.sha256 + '.part')
        for path in (target, candidate):
            if _is_link(path) or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
                raise UpdateError('Небезопасный файл загрузки.')
        if target.exists():
            _verify_app_package(target, update)
            if progress:
                progress(update.size, update.size)
            return target
        partial = candidate
        if not partial.exists():
            with partial.open('xb'):
                pass
        if partial.stat().st_size > update.size:
            raise UpdateError('Сохранённая загрузка больше ожидаемого пакета.')
        if progress:
            progress(partial.stat().st_size, update.size)
        with nullcontext(client) if client is not None else _client() as session:
            for attempt in range(3):
                if partial.stat().st_size == update.size:
                    break
                try:
                    _transfer_app_update(session, update, partial, progress)
                    break
                except httpx.TransportError:
                    if attempt == 2:
                        retain = partial.stat().st_size > 0
                        if retain:
                            raise UpdateDownloadInterrupted(partial.stat().st_size, update.size) from None
                        raise UpdateError('Не удалось скачать обновление. Попробуйте позже.') from None
                    time.sleep(attempt + 1)
        _verify_app_package(partial, update)
        partial.replace(target)
        return target
    except (httpx.HTTPError, OSError, ReleaseError, zipfile.BadZipFile, RuntimeError) as error:
        raise UpdateError('Не удалось скачать обновление. Текущая версия продолжит работать.') from None
    finally:
        if partial is not None and not retain:
            partial.unlink(missing_ok=True)


class UpdateManager:
    """One update job per installation; public state contains no local paths."""

    def __init__(self, root: Path, version: str, *, install_supported: bool = False):
        self.root = root
        self.version = version
        self.install_supported = install_supported
        self._lock = threading.RLock()
        self._update: AvailableUpdate | None = None
        self._phase = "idle"
        self._message = ""
        self._progress = 0
        self._last_check: float | None = None
        self._downloaded: Path | None = None
        self._lease = None

    def status(self) -> dict:
        with self._lock:
            return {"current_version": self.version, "phase": self._phase,
                    "available_version": self._update.version if self._update else None,
                    "download_bytes": self._progress,
                    "total_bytes": self._update.size if self._update else None,
                    "message": self._message, "install_supported": self.install_supported,
                    "can_resume": bool(_partial_update_bytes(self._update, self.root / "Updates"))}

    def check(self, *, force: bool = False) -> dict:
        with self._lock:
            if self._phase in {"checking", "downloading", "ready", "installing"}:
                return self.status()
            if not force and self._last_check is not None and time.monotonic() - self._last_check < 6 * 3600:
                return self.status()
            self._phase = "checking"
            self._message = "Проверяем обновления…"
        try:
            update = fetch_latest_update(self.version)
        except UpdateError as error:
            with self._lock:
                self._phase = "error"
                self._message = str(error)
        else:
            with self._lock:
                self._update = update
                self._progress = _partial_update_bytes(update, self.root / "Updates")
                self._phase = "available" if update else "current"
                self._message = f"Доступно обновление {update.version}" if update else "У вас последняя версия Tonight"
        finally:
            with self._lock:
                self._last_check = time.monotonic()
        return self.status()

    def reserve_download(self) -> AvailableUpdate:
        with self._lock:
            if not self.install_supported:
                raise UpdateError("Обновление одной кнопкой доступно в переносимой версии для Windows.")
            if self._phase in {"downloading", "ready", "installing", "checking"}:
                raise UpdateError("Обновление уже выполняется. Подождите немного.")
            if self._update is None:
                raise UpdateError("Сначала проверьте доступность обновления.")
            try:
                self._lease = acquire_update_lease(self.root)
            except UpdateGuardError as error:
                raise UpdateError(str(error)) from None
            self._phase = "downloading"
            self._message = "Скачиваем обновление…"
            self._progress = _partial_update_bytes(self._update, self.root / "Updates")
            return self._update

    def download_reserved(self, update: AvailableUpdate) -> Path | None:
        def progress(received: int, total: int) -> None:
            with self._lock:
                self._progress = received
        try:
            path = download_update(update, self.root / "Updates", progress=progress)
        except UpdateError as error:
            self.fail(str(error))
            return None
        with self._lock:
            self._downloaded = path
            self._phase = "ready"
            self._message = "Обновление скачано и проверено"
        return path

    def mark_installing(self) -> None:
        with self._lock:
            self._phase = "installing"
            self._message = "Обновляем Tonight — приложение откроется снова"

    def fail(self, message: str) -> None:
        with self._lock:
            if self._lease is not None:
                self._lease.close()
                self._lease = None
            self._phase = "error"
            self._message = message
