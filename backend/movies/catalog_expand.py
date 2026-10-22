"""Bounded, resumable-by-catalog TMDB additions; no personal-data upload."""
from datetime import date
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import socket
import sqlite3
import ssl
import tempfile
import threading
import time

import httpx
import certifi

from backend.catalog_database import merge_catalog_movies
from backend.backups import create_backup
from backend.catalog_media import MAX_IMAGE_BYTES, sanitize_catalog_image
from backend.catalog_package import _movies
from backend.catalog_recovery import checked
from backend.database.db import connect
from backend.movies.genres import normalize_genres
from backend.movies.trailers import select_youtube_trailer
from backend.update_guard import acquire_update_lease
from scripts.import_tmdb import verified_availability

FEEDS = ('/movie/top_rated', '/movie/popular', '/trending/movie/week')


class ExpansionError(ValueError):
    pass


class _ExpansionCancelled(Exception):
    pass


def tmdb_client():
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs()
    return httpx.Client(timeout=httpx.Timeout(20, connect=10), trust_env=False, verify=context)


def _error_chain(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def _certificate_error(error):
    return any(isinstance(item, ssl.SSLCertVerificationError)
               or 'CERTIFICATE_VERIFY_FAILED' in str(item) for item in _error_chain(error))


def _failure(error):
    if isinstance(error, ExpansionError):
        return 'tmdb_response', str(error)
    if _certificate_error(error):
        return 'certificate', 'Не удалось проверить сертификат TMDB. Проверьте дату и время Windows и настройки проверки HTTPS в антивирусе.'
    if any(isinstance(item, socket.gaierror) for item in _error_chain(error)):
        return 'dns', 'Windows не удалось найти api.themoviedb.org. Проверьте DNS и запись этого адреса в hosts.'
    if isinstance(error, httpx.TimeoutException):
        return 'timeout', 'TMDB не ответил вовремя после трёх попыток. Проверьте доступ к api.themoviedb.org и повторите загрузку.'
    if isinstance(error, httpx.TransportError):
        return 'connection', 'Не удалось установить устойчивое соединение с api.themoviedb.org. Проверьте доступ для Tonight в антивирусе и сетевые настройки Windows.'
    if isinstance(error, httpx.HTTPStatusError):
        return 'http', f'TMDB вернул ошибку HTTP {error.response.status_code}. Попробуйте повторить загрузку позже.'
    if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        return 'invalid_response', 'Вместо данных TMDB получен неподдерживаемый ответ. Проверьте доступ к api.themoviedb.org.'
    if isinstance(error, sqlite3.Error):
        return 'database', 'Не удалось сохранить данные каталога. Проверьте свободное место и доступ Tonight к папке data.'
    if isinstance(error, OSError):
        return 'storage', 'Не удалось записать файлы загрузки или резервную копию. Проверьте свободное место и доступ Tonight к папке data.'
    return 'internal', 'Не удалось обработать данные TMDB. Подробности сохранены в data/logs/tmdb-download.log.'


class CatalogExpansion:
    def __init__(self, root, database, token, *, client_factory=None):
        self.root, self.database, self.token = Path(root), Path(database), token
        self.client_factory = client_factory or tmdb_client
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.lease = None
        self.worker_started = False
        self.state = dict(phase='idle', target=50, added=0, posters=0, scanned=0, image_errors=0, error_code=None, message='')

    def status(self):
        with self.lock:
            return dict(self.state, available=bool(self.token()), can_cancel=self.state['phase']=='running')

    def reserve(self, count):
        if type(count) is not int or count not in (20, 50, 100):
            raise ExpansionError('Выберите 20, 50 или 100 фильмов.')
        with self.lock:
            if self.lease is not None:
                raise ExpansionError('Загрузка уже идёт.')
            if not self.token():
                raise ExpansionError('Ключ приложения недоступен. Установите актуальную сборку Tonight.')
            self.lease = acquire_update_lease(self.root)
            self.worker_started = False
            self.cancelled.clear()
            self.state = dict(phase='running', target=count, added=0, posters=0, scanned=0, image_errors=0,
                              error_code=None, message='Ищем новые фильмы в TMDB…')

    def cancel(self):
        with self.lock:
            if self.lease is not None:
                self.cancelled.set()
                self.state['message'] = 'Останавливаем после текущего фильма…'
        return self.status()

    def _get(self, client, path, **params):
        token = self.token()
        headers = {'Authorization': 'Bearer '+token} if not re.fullmatch('[a-fA-F0-9]{32}', token) else {}
        if not headers:
            params['api_key'] = token
        for attempt in range(3):
            if self.cancelled.is_set():
                raise _ExpansionCancelled()
            try:
                with client.stream('GET', 'https://api.themoviedb.org/3'+path,
                                   params=params, headers=headers, follow_redirects=False) as response:
                    if response.status_code == 401:
                        raise ExpansionError('TMDB отклонил ключ приложения. Проверьте личный TMDB_READ_TOKEN в .env; пустое значение использует общий ключ Tonight.')
                    if response.status_code == 403:
                        raise ExpansionError('TMDB запретил доступ к API. Проверьте доступность api.themoviedb.org из этой сети.')
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < 2:
                            response.close()
                            self._retry(attempt)
                            continue
                        raise ExpansionError('TMDB временно ограничил загрузку. Попробуйте позже.')
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 4*1024*1024:
                            raise ExpansionError('Ответ TMDB слишком большой.')
                    result = json.loads(body)
                    if not isinstance(result, dict):
                        raise ExpansionError('TMDB вернул неподдерживаемый ответ.')
                    return result
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
                if attempt == 2 or _certificate_error(error):
                    raise
                self._retry(attempt)

    def _retry(self, attempt):
        with self.lock:
            self.state['message'] = f'Связь с TMDB прервалась. Повторяем запрос: попытка {attempt+2} из 3…'
        if self.cancelled.wait(attempt+1):
            raise _ExpansionCancelled()

    def _record_failure(self, error, code):
        # Record exception categories, never exception text, URLs or credentials.
        record = dict(time=datetime.now(timezone.utc).isoformat(), code=code,
                      exceptions=[type(item).__name__ for item in _error_chain(error)],
                      added=self.state['added'], scanned=self.state['scanned'])
        if isinstance(error, httpx.HTTPStatusError):
            record['http_status'] = error.response.status_code
        try:
            path = checked(self.root, 'data/logs/tmdb-download.log')
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > 256*1024:
                path.replace(checked(self.root, 'data/logs/tmdb-download.log.1'))
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False)+'\n')
        except (OSError, ValueError):
            pass

    def _poster(self, client, movie_id, image):
        if not isinstance(image, str) or not re.fullmatch(r'/[A-Za-z0-9_\-]+\.(jpg|png|webp)', image):
            return
        extension = Path(image).suffix
        folder = checked(self.root, 'data/posters')
        folder.mkdir(parents=True, exist_ok=True)
        if any(checked(self.root, f'data/posters/{movie_id}{ext}').exists() for ext in ('.jpg','.jpeg','.png','.webp')):
            return
        try:
            with client.stream('GET', 'https://image.tmdb.org/t/p/w500'+image, follow_redirects=False) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>MAX_IMAGE_BYTES:
                        raise ValueError('Image too large')
            content = sanitize_catalog_image(bytes(body), extension)
            descriptor, temporary = tempfile.mkstemp(prefix='.poster-', dir=folder)
            temporary = Path(temporary)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(content)
                os.link(temporary, checked(self.root, f'data/posters/{movie_id}{extension}'))
            finally:
                temporary.unlink(missing_ok=True)
            with self.lock:
                self.state['posters'] += 1
        except (httpx.HTTPError, OSError, ValueError):
            with self.lock:
                self.state['image_errors'] += 1

    def _row(self, detail):
        evidence = verified_availability(detail)
        release = detail.get('release_date') or ''
        if (not evidence or detail.get('adult') is True or not detail.get('runtime') or
                not re.fullmatch(r'\d{4}-\d{2}-\d{2}', release) or date.fromisoformat(release)>date.today()):
            return None
        trailer = select_youtube_trailer(detail.get('videos', {}).get('results', []), []) or {}
        row = dict(id='tmdb-'+str(detail['id']), tmdb_id=detail['id'], title=evidence['russian_title'],
                   original_title=detail.get('original_title'), year=int(release[:4]), release_date=release,
                   genres=normalize_genres([g['name'].lower() for g in detail.get('genres', [])]),
                   overview=detail.get('overview') or '', runtime=detail['runtime'], rating=detail.get('vote_average'),
                   vote_count=detail.get('vote_count', 0), keywords=[k['name'] for k in detail.get('keywords', {}).get('keywords', [])[:12]],
                   director=next((c['name'] for c in detail.get('credits', {}).get('crew', []) if c.get('job')=='Director'), None),
                   cast_names=[c['name'] for c in detail.get('credits', {}).get('cast', [])[:6]],
                   trailer_key=trailer.get('key'), trailer_language=trailer.get('language'),
                   catalog_sources=['manual_tmdb'], source='tmdb', **evidence)
        _movies([row])
        return row

    def run(self):
        with self.lock:
            if self.lease is None or self.worker_started:
                return
            self.worker_started = True
            lease = self.lease
        try:
            create_backup(self.database, checked(self.root, 'data/backups'), prefix='before-tmdb-additions')
            with self.client_factory() as client:
                for turn in range(150):
                    if self.cancelled.is_set() or self.state['added']>=self.state['target']:
                        break
                    source = turn % len(FEEDS)
                    key = f'tmdb_expand_page_{source}'
                    with connect(self.database) as db:
                        saved = db.execute('SELECT value FROM app_meta WHERE key=?', (key,)).fetchone()
                        page = max(1, min(500, int(saved[0]))) if saved else 1
                        known = {r['tmdb_id']: r['id'] for r in db.execute('SELECT id,tmdb_id FROM movies WHERE tmdb_id IS NOT NULL')}
                    response = self._get(client, FEEDS[source], language='ru-RU', page=page)
                    exhausted_page = True
                    for summary in response.get('results', []):
                        if self.cancelled.is_set() or self.state['added']>=self.state['target']:
                            exhausted_page = False
                            break
                        tmdb_id = summary.get('id')
                        if type(tmdb_id) is not int or tmdb_id<=0 or summary.get('adult') is True:
                            continue
                        with self.lock:
                            self.state['scanned'] += 1
                        existing = known.get(tmdb_id)
                        if existing:
                            self._poster(client, existing, summary.get('poster_path'))
                            continue
                        detail = self._get(client, '/movie/'+str(tmdb_id), language='ru-RU',
                                           append_to_response='credits,keywords,videos,translations,release_dates')
                        if detail.get('id')!=tmdb_id:
                            continue
                        row = self._row(detail)
                        if row is None:
                            continue
                        with connect(self.database) as db:
                            # Preserve legacy titles and personal edits; identity resolver
                            # also handles a starter card for the same TMDB movie.
                            before = db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]
                            db.execute('BEGIN IMMEDIATE')
                            movie_id = merge_catalog_movies(db, [row])[row['id']]
                            added = db.execute('SELECT COUNT(*) FROM movies').fetchone()[0] - before
                        known[tmdb_id] = movie_id
                        with self.lock:
                            self.state['added'] += added
                            self.state['message'] = 'Добавляем фильмы и сохраняем постеры…'
                        self._poster(client, movie_id, detail.get('poster_path'))
                        self.cancelled.wait(.1)
                    if exhausted_page:
                        next_page = page+1 if page < min(500, int(response.get('total_pages') or 500)) else 1
                        with connect(self.database) as db:
                            db.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)', (key,str(next_page)))
                with self.lock:
                    self.state['phase'] = 'cancelled' if self.cancelled.is_set() else 'done'
                    self.state['message'] = ('Загрузка остановлена. Добавленные фильмы сохранены.' if self.cancelled.is_set()
                                             else 'Готово! Новые фильмы уже доступны для выбора.')
                    if self.state['phase']=='done' and self.state['added']<self.state['target']:
                        self.state['message'] = 'Доступную подборку проверили. Позже можно поискать ещё; добавленные фильмы сохранены.'
        except _ExpansionCancelled:
            with self.lock:
                self.state['phase'] = 'cancelled'
                self.state['message'] = 'Загрузка остановлена. Добавленные фильмы сохранены.'
        except Exception as error:
            code, message = _failure(error)
            self._record_failure(error, code)
            with self.lock:
                self.state['phase'] = 'error'
                self.state['error_code'] = code
                self.state['message'] = message + ' Добавленные фильмы сохранены.'
        finally:
            with self.lock:
                lease.close()
                self.lease = None
