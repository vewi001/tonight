"""Read-only identity preflight for validated catalog rows; never rewrites history."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Any

from backend.catalog_package import CatalogPackageError


def _signature(movie):
    name = (movie.get('original_title') or '').strip() or movie['title'].strip()
    return name.casefold(),movie['year']


def _compatible(left,right):
    first,second = left.get('tmdb_id'),right.get('tmdb_id')
    if first is not None and second is not None:
        return first==second
    return _signature(left)==_signature(right)


class _IdentityIndex:
    def __init__(self,rows):
        self.ids = {}
        self.tmdb = {}
        self.signatures = defaultdict(list)
        for row in rows:
            self.add(row)

    def add(self,row):
        key,tmdb_id = row['id'].casefold(),row.get('tmdb_id')
        if key in self.ids or (tmdb_id is not None and tmdb_id in self.tmdb):
            raise CatalogPackageError('В локальном каталоге неоднозначные идентификаторы')
        # Own the mapping; none of the original rows is ever modified.
        record = dict(row)
        self.ids[key] = record
        if tmdb_id is not None:
            self.tmdb[tmdb_id] = record
        self.signatures[_signature(record)].append(record)

    def resolve(self,row):
        by_id = self.ids.get(row['id'].casefold())
        by_tmdb = self.tmdb.get(row.get('tmdb_id'))
        if by_tmdb is not None:
            if by_id is not None and by_id['id']!=by_tmdb['id']:
                raise CatalogPackageError('Идентификатор пакета занят другим фильмом')
            return by_tmdb['id']
        if by_id is not None:
            if not _compatible(by_id,row):
                raise CatalogPackageError('Пакет пытается изменить идентичность существующего фильма')
            return by_id['id']
        candidates = [movie for movie in self.signatures.get(_signature(row),()) if _compatible(movie,row)]
        if len(candidates)>1:
            raise CatalogPackageError('Фильм нельзя однозначно сопоставить с локальным каталогом')
        return candidates[0]['id'] if candidates else row['id']


def resolve_catalog_ids(existing: Iterable[Mapping[str,Any]], incoming: Iterable[Mapping[str,Any]]) -> dict[str,str]:
    """Return source-id -> canonical local-id for a whole validated batch.

    Both inputs must have valid id/title/year/tmdb_id types. A conflict rejects
    the entire preflight before any write. New rows are indexed provisionally
    to catch aliases within the incoming batch too. No input is mutated.
    Caller must use one consistent database snapshot and recheck under its
    installation lock before applying this mapping to movies and media.
    """
    index = _IdentityIndex(existing)
    result,claimed = {},set()
    for row in incoming:
        local_id = index.resolve(row)
        if row['id'] in result or local_id.casefold() in claimed:
            raise CatalogPackageError('Несколько карточек пакета относятся к одному фильму')
        result[row['id']] = local_id
        claimed.add(local_id.casefold())
        if local_id.casefold() not in index.ids:
            index.add(row)
    return result
