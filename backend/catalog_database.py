"""Transactional movie/baseline merge; not a media installer or success marker."""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Mapping, Any

from backend.catalog_identity import resolve_catalog_ids
from backend.catalog_merge_policy import EDITABLE_FIELDS, plan_field_updates
from backend.catalog_package import ARRAY_FIELDS, FIELDS, CatalogPackageError, _movies


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def _normalize(row):
    result = dict(row)
    for field in ARRAY_FIELDS:
        value = result.get(field)
        if value is None:
            continue
        try:
            decoded = json.loads(value)
        except (TypeError,ValueError):
            raise CatalogPackageError('В локальной карточке повреждён список признаков') from None
        if not isinstance(decoded,list) or any(not isinstance(item,str) for item in decoded):
            raise CatalogPackageError('В локальной карточке повреждён список признаков')
        result[field] = decoded
    return result


def _sql_value(field,value):
    return _json(value) if field in ARRAY_FIELDS and value is not None else value


def merge_catalog_movies(db: sqlite3.Connection, movies: Iterable[Mapping[str,Any]]) -> dict[str,str]:
    """Merge validated public fields under a caller-owned BEGIN IMMEDIATE.

    Returns source-id -> stable local-id. SAVEPOINT rolls back this entire
    merge on failure, never commits the caller's transaction. Requires Tonight
    schema, sqlite3.Row factory and foreign keys ON. Caller owns update lock,
    backup, media staging/recovery and final version/date commit. Not exposed
    directly to HTTP or invoked on live user data without that installer.
    """
    if not db.in_transaction or not db.execute('PRAGMA foreign_keys').fetchone()[0]:
        raise CatalogPackageError('Слияние требует транзакцию и защиту ссылок базы')
    incoming = [dict(row) for row in movies]
    _movies(incoming)
    db.execute('SAVEPOINT tonight_catalog_merge')
    try:
        existing = [_normalize(row) for row in db.execute(f"SELECT {','.join(FIELDS)} FROM movies")]
        mapping = resolve_catalog_ids(existing,incoming)
        current = {row['id']:row for row in existing}
        db.execute('''CREATE TABLE IF NOT EXISTS catalog_field_baselines (
            movie_id TEXT PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
            fields TEXT NOT NULL
        )''')
        baselines = {}
        for row in db.execute('SELECT movie_id,fields FROM catalog_field_baselines'):
            try:
                fields = json.loads(row['fields'])
                if not isinstance(fields,dict) or set(fields)-EDITABLE_FIELDS:
                    raise ValueError
            except (TypeError,ValueError):
                raise CatalogPackageError('Повреждены сведения о прошлых обновлениях каталога') from None
            baselines[row['movie_id']] = fields
        for row in incoming:
            local_id = mapping[row['id']]
            if local_id not in current:
                values = dict(row,id=local_id)
                columns = list(values)
                db.execute(f"INSERT INTO movies({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                           [_sql_value(field,values[field]) for field in columns])
                baseline = {field:value for field,value in row.items() if field in EDITABLE_FIELDS and value is not None}
            else:
                local = current[local_id]
                plan = plan_field_updates(local,row,baselines.get(local_id,{}))
                changes = dict(plan.changes)
                if local.get('tmdb_id') is None and row.get('tmdb_id') is not None:
                    changes['tmdb_id'] = row['tmdb_id']
                if changes:
                    db.execute(f"UPDATE movies SET {','.join(field+'=?' for field in changes)} WHERE id=?",
                               [_sql_value(field,value) for field,value in changes.items()]+[local_id])
                baseline = plan.baseline
            db.execute('''INSERT INTO catalog_field_baselines(movie_id,fields) VALUES(?,?)
                ON CONFLICT(movie_id) DO UPDATE SET fields=excluded.fields''',(local_id,_json(baseline)))
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise CatalogPackageError('Нарушены ссылки локальных данных; обновление не применено')
        db.execute('RELEASE SAVEPOINT tonight_catalog_merge')
        return mapping
    except BaseException:
        db.execute('ROLLBACK TO SAVEPOINT tonight_catalog_merge')
        db.execute('RELEASE SAVEPOINT tonight_catalog_merge')
        raise
