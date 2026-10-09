"""Public JSON catalog packages; never distribute or execute a user's SQLite."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import zipfile

from backend.release import MAX_RELEASE_BYTES, MAX_RELEASE_FILES, ReleaseError, _is_link, _safe_relative
from backend.movies.trailers import YOUTUBE_KEY
from backend.catalog_media import MAX_IMAGE_BYTES, CatalogMediaError, sanitize_catalog_image, validate_catalog_image

MANIFEST = 'tonight-catalog.json'
MAX_MOVIES_BYTES = 32 * 1024 * 1024
MAX_MOVIES = 20_000
VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
FIELDS = ('id','title','original_title','year','release_date','genres','overview','runtime',
          'rating','vote_count','keywords','director','cast_names','franchise_key','franchise_order',
          'tmdb_id','trailer_key','trailer_language','catalog_sources','source')
ARRAY_FIELDS = {'genres','keywords','cast_names','catalog_sources'}
INT_RANGES = {'year':(1888,2200),'runtime':(1,1440),'vote_count':(0,2**63-1),
              'franchise_order':(1,10000),'tmdb_id':(1,2**63-1)}
EXTENSIONS = {'.jpg','.jpeg','.png','.webp'}


class CatalogPackageError(ValueError):
    """A catalog is invalid; no installation should be attempted."""


class CatalogCompatibilityError(CatalogPackageError):
    """A canonical required app version, never arbitrary manifest text."""
    def __init__(self, minimum: str):
        self.minimum = _version(minimum)
        super().__init__('Для этого каталога сначала обновите Tonight')


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise CatalogPackageError('Описание каталога содержит повторяющиеся поля')
        result[key] = value
    return result


@dataclass(frozen=True)
class CatalogPackage:
    version: str
    min_app_version: str
    created_at: str
    movies: tuple[dict, ...]
    media_files: tuple[str, ...]


def _version(value):
    if not isinstance(value,str) or len(value)>32 or not VERSION.fullmatch(value):
        raise CatalogPackageError('Некорректная версия каталога или приложения')
    return value


def _date(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except (TypeError,ValueError,AttributeError):
        raise CatalogPackageError('Дата пакета должна быть указана в UTC') from None
    return value


def _movies(values):
    if not isinstance(values,list) or not values or len(values)>MAX_MOVIES:
        raise CatalogPackageError('Некорректное количество фильмов в пакете')
    seen, tmdb = set(), set()
    for movie in values:
        if not isinstance(movie,dict) or set(movie)-set(FIELDS) or not {'id','title','year','genres'} <= set(movie):
            raise CatalogPackageError('В карточке есть неизвестные или отсутствуют обязательные поля')
        identifier = movie['id']
        if not isinstance(identifier,str) or not IDENTIFIER.fullmatch(identifier) or identifier.casefold() in seen:
            raise CatalogPackageError('Некорректный или повторяющийся идентификатор фильма')
        seen.add(identifier.casefold())
        try:
            _safe_relative(identifier+'.jpg')
        except ReleaseError:
            raise CatalogPackageError('Идентификатор фильма небезопасен для локального медиа') from None
        for field,value in movie.items():
            if value is None and field not in {'id','title','year','genres'}:
                continue
            if field in ARRAY_FIELDS:
                if not isinstance(value,list) or len(value)>100 or any(not isinstance(item,str) or len(item)>300 for item in value):
                    raise CatalogPackageError('Некорректный список признаков фильма')
            elif field in INT_RANGES:
                lower,upper = INT_RANGES[field]
                if type(value) is not int or not lower<=value<=upper:
                    raise CatalogPackageError('Некорректное числовое поле фильма')
            elif field=='rating':
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=10:
                    raise CatalogPackageError('Некорректный рейтинг фильма')
            elif not isinstance(value,str) or len(value)>20_000:
                raise CatalogPackageError('Некорректное текстовое поле фильма')
        if not movie['title'].strip():
            raise CatalogPackageError('У фильма отсутствует название')
        if movie.get('trailer_key') is not None and not YOUTUBE_KEY.fullmatch(movie['trailer_key']):
            raise CatalogPackageError('Некорректная ссылка на трейлер')
        tmdb_id = movie.get('tmdb_id')
        if tmdb_id is not None:
            if tmdb_id in tmdb:
                raise CatalogPackageError('Фильм TMDB повторяется в пакете')
            tmdb.add(tmdb_id)
    return tuple(values)


def _media_name(name, identifiers):
    path = _safe_relative(name)
    if len(path.parts)!=2 or path.parts[0] not in {'posters','backdrops'} or path.suffix not in EXTENSIONS or path.stem not in identifiers:
        raise CatalogPackageError('Файл не относится к медиа каталога')


def _clean_media(path):
    try:
        with path.open('rb') as source:
            content = source.read(MAX_IMAGE_BYTES+1)
        return sanitize_catalog_image(content,path.suffix)
    except CatalogMediaError:
        raise CatalogPackageError('Изображение каталога не прошло проверку') from None


def read_catalog_package(archive: Path, *, app_version: str | None = None) -> CatalogPackage:
    try:
        if archive.stat().st_size>MAX_RELEASE_BYTES:
            raise CatalogPackageError('Архив каталога слишком большой')
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            names = [entry.filename for entry in entries]
            if (len(names)>MAX_RELEASE_FILES or len(set(name.casefold() for name in names))!=len(names)
                    or sum(entry.file_size for entry in entries)>MAX_RELEASE_BYTES):
                raise CatalogPackageError('Пакет слишком большой или содержит повторяющиеся файлы')
            for entry in entries:
                _safe_relative(entry.filename)
                if entry.is_dir() or stat.S_ISLNK(entry.external_attr>>16) or entry.flag_bits&1:
                    raise CatalogPackageError('В пакете есть ссылка, папка или зашифрованный файл')
            manifest_entry = bundle.getinfo(MANIFEST)
            if manifest_entry.file_size>2*1024*1024 or bundle.getinfo('movies.json').file_size>MAX_MOVIES_BYTES:
                raise CatalogPackageError('Описание каталога слишком большое')
            manifest = json.loads(bundle.read(MANIFEST),object_pairs_hook=_unique_object)
            required = {'product','kind','format','version','min_app_version','created_at','movie_count','files'}
            if (not isinstance(manifest,dict) or set(manifest)!=required or manifest['product']!='Tonight'
                    or manifest['kind']!='catalog' or type(manifest['format']) is not int or manifest['format']!=1):
                raise CatalogPackageError('Пакет не предназначен для каталога Tonight')
            version, minimum = _version(manifest['version']), _version(manifest['min_app_version'])
            if app_version is not None:
                current = tuple(map(int,_version(app_version).split('.')))
                required_version = tuple(map(int,minimum.split('.')))
                if current<required_version:
                    raise CatalogCompatibilityError(minimum)
            created = _date(manifest['created_at'])
            files = manifest['files']
            if not isinstance(files,dict) or set(files)|{MANIFEST}!=set(names) or MANIFEST in files:
                raise CatalogPackageError('Состав пакета не совпадает с манифестом')
            for name,expected in files.items():
                if (not isinstance(expected,dict) or set(expected)!={'size','sha256'} or type(expected['size']) is not int
                        or expected['size']!=bundle.getinfo(name).file_size or not isinstance(expected['sha256'],str)
                        or not re.fullmatch('[a-f0-9]{64}',expected['sha256'])):
                    raise CatalogPackageError('Некорректное описание файла каталога')
                with bundle.open(name) as source:
                    if hashlib.file_digest(source,'sha256').hexdigest()!=expected['sha256']:
                        raise CatalogPackageError('Файл каталога не прошёл проверку')
            movies = _movies(json.loads(bundle.read('movies.json'),object_pairs_hook=_unique_object))
            if type(manifest['movie_count']) is not int or manifest['movie_count']!=len(movies):
                raise CatalogPackageError('Количество фильмов не совпадает с манифестом')
            identifiers = {movie['id'] for movie in movies}
            media = tuple(sorted(set(files)-{'movies.json'}))
            for name in media:
                _media_name(name,identifiers)
                if bundle.getinfo(name).file_size>MAX_IMAGE_BYTES:
                    raise CatalogPackageError('Изображение каталога слишком большое')
                try:
                    validate_catalog_image(bundle.read(name),Path(name).suffix)
                except CatalogMediaError:
                    raise CatalogPackageError('Изображение каталога не прошло проверку') from None
            return CatalogPackage(version,minimum,created,movies,media)
    except (OSError,KeyError,UnicodeDecodeError,json.JSONDecodeError,zipfile.BadZipFile,ReleaseError,RuntimeError):
        raise CatalogPackageError('Не удалось проверить пакет каталога') from None


def build_catalog_package(source_data: Path, output: Path, *, version: str, min_app_version: str,
                          created_at: str | None = None, include_media: bool = False,
                          media_rights_reviewed: bool = False) -> Path:
    version, minimum = _version(version), _version(min_app_version)
    created = _date(created_at or datetime.now(timezone.utc).isoformat(timespec='seconds'))
    if output.exists() or output.is_symlink():
        raise CatalogPackageError('Выходной архив уже существует')
    if include_media and not media_rights_reviewed:
        raise CatalogPackageError('Для включения медиа сначала подтвердите проверку прав')
    source = source_data/'tonight.db'
    if not source.is_file() or _is_link(source) or _is_link(source_data):
        raise CatalogPackageError('Источник каталога отсутствует или является ссылкой')
    try:
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory = sqlite3.Row
            available = {row[1] for row in db.execute('PRAGMA table_info(movies)')}
            columns = [field for field in FIELDS if field in available]
            if not {'id','title','year','genres'}<=set(columns):
                raise CatalogPackageError('В источнике нет необходимых полей фильмов')
            rows = db.execute('SELECT '+','.join(columns)+' FROM movies ORDER BY id LIMIT ?', (MAX_MOVIES+1,)).fetchall()
            movies = []
            for row in rows:
                movie = dict(row)
                for field in ARRAY_FIELDS & set(movie):
                    movie[field] = json.loads(movie[field]) if movie[field] is not None else []
                movies.append(movie)
        _movies(movies)
    except (sqlite3.Error,TypeError,json.JSONDecodeError):
        raise CatalogPackageError('Не удалось прочитать публичные данные фильмов') from None
    payload = json.dumps(movies,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(payload)>MAX_MOVIES_BYTES:
        raise CatalogPackageError('Описание каталога слишком большое')
    files = {'movies.json': {'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}}
    media = {}
    if include_media:
        for folder in ('posters','backdrops'):
            directory = source_data/folder
            if _is_link(directory):
                raise CatalogPackageError('Папка медиа не может быть ссылкой')
            if not directory.is_dir():
                continue
            for movie in movies:
                for extension in sorted(EXTENSIONS):
                    path = directory/(movie['id']+extension)
                    if _is_link(path):
                        raise CatalogPackageError('Медиа не может быть ссылкой')
                    if path.is_file():
                        name = folder+'/'+path.name
                        media[name] = path
                        content = _clean_media(path)
                        files[name] = {'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    if len(files)+1>MAX_RELEASE_FILES or sum(item['size'] for item in files.values())>MAX_RELEASE_BYTES:
        raise CatalogPackageError('Каталог превышает ограничения размера')
    manifest = {'product':'Tonight','kind':'catalog','format':1,'version':version,'min_app_version':minimum,
                'created_at':created,'movie_count':len(movies),'files':files}
    output.parent.mkdir(parents=True,exist_ok=True)
    handle,temporary = tempfile.mkstemp(prefix='.catalog-package-',suffix='.zip',dir=output.parent)
    os.close(handle)
    stage = Path(temporary)
    try:
        with zipfile.ZipFile(stage,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
            content = {MANIFEST:json.dumps(manifest,ensure_ascii=False,sort_keys=True).encode(),'movies.json':payload}
            for name in sorted(set(content)|set(media)):
                info = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                if name in content:
                    bundle.writestr(info,content[name])
                else:
                    # Repeat bounded sanitizing rather than retain all images in RAM.
                    # If the source changed meanwhile, final manifest validation fails.
                    bundle.writestr(info,_clean_media(media[name]))
        read_catalog_package(stage)
        # Atomic publication without overwriting an output created concurrently.
        os.link(stage,output)
    finally:
        stage.unlink(missing_ok=True)
    return output
