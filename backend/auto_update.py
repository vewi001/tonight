"""Public GitHub release discovery and verified, streamed update downloads."""
from __future__ import annotations

import hashlib
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

from backend.release import MAX_RELEASE_BYTES, ReleaseError, read_release

LATEST_URL = "https://api.github.com/repos/vewi001/tonight/releases/latest"
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


def fetch_latest_update(current_version: str, *, client: httpx.Client | None = None) -> AvailableUpdate | None:
    try:
        with nullcontext(client) if client is not None else _client() as session:
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


def download_update(update: AvailableUpdate, destination: Path, *, client: httpx.Client | None = None,
                    progress: Callable[[int, int], None] | None = None) -> Path:
    """Download a complete, validated package; never install from a partial file."""
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / update.name
    partial = destination / (update.name + ".part")
    try:
        with nullcontext(client) if client is not None else _client() as session:
            url = update.url
            for _ in range(6):
                if not _download_url_allowed(url):
                    raise UpdateError("GitHub направил загрузку по неожиданному адресу.")
                with session.stream("GET", url, headers={"User-Agent": "Tonight-updater", "Accept-Encoding": "identity"},
                                    follow_redirects=False) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise UpdateError("GitHub не указал адрес загрузки.")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    total = 0
                    digest = hashlib.sha256()
                    with partial.open("wb") as output:
                        for chunk in response.iter_bytes(64 * 1024):
                            total += len(chunk)
                            if total > update.size:
                                raise UpdateError("Размер скачанного обновления не совпал. Попробуйте снова.")
                            digest.update(chunk)
                            output.write(chunk)
                            if progress:
                                progress(total, update.size)
                    if total != update.size or digest.hexdigest() != update.sha256:
                        raise UpdateError("Скачанный файл не прошёл проверку. Попробуйте снова.")
                    release = read_release(partial)
                    if release.version != update.version or "Tonight.exe" not in release.files:
                        raise UpdateError("Содержимое пакета не соответствует версии Tonight.")
                    with zipfile.ZipFile(partial) as bundle:
                        if bundle.testzip() is not None:
                            raise UpdateError("Архив обновления повреждён. Попробуйте снова.")
                    partial.replace(target)
                    return target
            raise UpdateError("Не удалось найти файл обновления на GitHub.")
    except (httpx.HTTPError, OSError, ReleaseError, zipfile.BadZipFile, RuntimeError):
        raise UpdateError("Не удалось скачать обновление. Текущая версия продолжит работать.") from None
    finally:
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

    def status(self) -> dict:
        with self._lock:
            return {"current_version": self.version, "phase": self._phase,
                    "available_version": self._update.version if self._update else None,
                    "download_bytes": self._progress,
                    "total_bytes": self._update.size if self._update else None,
                    "message": self._message, "install_supported": self.install_supported}

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
            self._phase = "downloading"
            self._message = "Скачиваем обновление…"
            self._progress = 0
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
            self._phase = "error"
            self._message = message
