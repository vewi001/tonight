"""Movie Match state in the existing sessions registry, serialized by SQLite.

Browser credentials and individual votes never leave this service. A room link
grants one free seat, not access to either of the computer's personal profiles.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.database.db import db_session, dumps, loads
from backend.movies.catalog import is_released, row_to_movie
from backend.movies.genres import normalize_genres
from backend.recommendation.personal import rank_movies
from backend.recommendation.exclusions import filter_movies, load_policy


class MatchError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Filters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_runtime: int | None = Field(None, ge=1, le=1440)
    min_year: int | None = Field(None, ge=1888, le=2100)
    max_year: int | None = Field(None, ge=1888, le=2100)
    min_rating: float = Field(0, ge=0, le=10)
    included_genres: list[str] = Field(default_factory=list, max_length=40)
    excluded_genres: list[str] = Field(default_factory=list, max_length=40)
    exclude_watched: bool = True

    @model_validator(mode='after')
    def validate_conditions(self):
        self.included_genres = normalize_genres(self.included_genres)
        self.excluded_genres = normalize_genres(self.excluded_genres)
        if self.min_year and self.max_year and self.min_year > self.max_year:
            raise ValueError('Начальный год должен быть не позже конечного')
        if set(self.included_genres) & set(self.excluded_genres):
            raise ValueError('Жанр нельзя одновременно включить и исключить. Согласуйте условия.')
        return self


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    op: Literal['ready', 'filters', 'vote', 'propose', 'confirm', 'cancel', 'leave', 'close', 'save']
    version: int = Field(ge=1)
    movie_id: str | None = Field(None, max_length=160)
    vote: Literal['yes', 'no', 'watched'] | None = None
    filters: Filters | None = None


def now():
    return datetime.now(timezone.utc)


def credential(token):
    if not token or not 32 <= len(token) <= 160:
        raise MatchError('Откройте приглашение в том же браузере или создайте комнату.', 403)
    return hashlib.sha256(token.encode()).hexdigest()


def read(db, sid):
    row = db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
    data = loads(row['match_data'], {}) if row else {}
    if not data:
        raise MatchError('Комната не найдена. Попросите новое приглашение.', 404)
    return data


def member(data, token):
    key = credential(token)
    for i, person in enumerate(data['members']):
        if secrets.compare_digest(person['key'], key):
            return i
    raise MatchError('Этот браузер не участвует в комнате.', 403)


def available(data):
    if now().isoformat() >= data['expires_at']:
        raise MatchError('Срок комнаты истёк. Создайте новую.', 410)
    if data['phase'] in {'closed', 'left'}:
        raise MatchError('Совместный выбор завершён. Создайте новую комнату.', 410)


def write(db, sid, data):
    data['version'] += 1
    db.execute('UPDATE sessions SET match_data=?,updated_at=? WHERE id=?', (dumps(data), now().isoformat(), sid))


def initialize_room(sid, token, profile=None, *, db=None):
    if db is None:
        with db_session() as connection:
            connection.execute('BEGIN IMMEDIATE')
            initialize_room(sid, token, profile, db=connection)
        return snapshot(sid, token)
    key = credential(token)
    # Old room credentials/votes are removed after seven days; history rows
    # and normal Tonight sessions remain intact.
    db.execute("UPDATE sessions SET match_data='{}' WHERE match_data!='{}' AND json_extract(match_data,'$.expires_at') < ?", ((now()-timedelta(days=6)).isoformat(),))
    data = {'room': secrets.token_urlsafe(24), 'version': 1, 'conditions_version': 1, 'phase': 'lobby',
            'expires_at': (now()+timedelta(hours=24)).isoformat(), 'filters': Filters().model_dump(),
            'members': [{'key': key, 'votes': {}, 'ready': False, 'saved': []}],
            'deck': [], 'proposal': None, 'confirmed': [], 'final': None,
            'profile': profile if profile in {'lera', 'nikita'} else None}
    permanent, temporary, watched = load_policy(db, [data['profile']], sid) if data['profile'] else ([], [], set())
    # Freeze private hard rules for this room. Editing the owner's profile
    # elsewhere must not silently change the guest's agreed conditions.
    data['policy'] = {'permanent': permanent, 'temporary': temporary, 'watched': sorted(watched)}
    db.execute('UPDATE sessions SET match_data=? WHERE id=?', (dumps(data), sid))

def join(room, token):
    key = credential(token)
    with db_session() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT id,match_data FROM sessions WHERE json_extract(match_data,'$.room')=?", (room,)).fetchone()
        if not row:
            raise MatchError('Приглашение недействительно или устарело. Попросите новую ссылку.', 404)
        data = loads(row['match_data'], {})
        available(data)
        if not any(secrets.compare_digest(p['key'], key) for p in data['members']):
            if len(data['members']) >= 2:
                raise MatchError('В комнате уже двое. Попросите создать новую комнату.')
            if data['phase'] != 'lobby':
                raise MatchError('Выбор уже начался.')
            data['members'].append({'key': key, 'votes': {}, 'ready': False, 'saved': []})
            # A newcomer must see and agree with the same conditions.
            for p in data['members']:
                p['ready'] = False
            data['conditions_version'] = data['version'] + 1
            write(db, row['id'], data)
        sid = row['id']
    return snapshot(sid, token)


def candidates(db, sid, data, *, ranked=False):
    from backend.recommendation.constraints import meets_conditions
    f = data['filters']
    movies = [row_to_movie(r) for r in db.execute('SELECT * FROM movies')]
    movies = [m for m in movies if is_released(m) and meets_conditions(m, f)]
    # Apply the owner's existing antirecommendations; never attach a guest to
    # the other local profile or write guest votes into Tonight IQ.
    policy = data.get('policy', {'permanent': [], 'temporary': [], 'watched': []})
    movies = filter_movies(movies, policy['permanent'], policy['temporary'], policy['watched'])
    watched = set(policy['watched']) if f['exclude_watched'] else set()
    watched |= {mid for p in data['members'] for mid, vote in p['votes'].items() if vote == 'watched'} if f['exclude_watched'] else set()
    movies = [m for m in movies if m['id'] not in watched]
    # Existing neutral ranking/diversity: no host's personal score dominates
    # the guest, and no recommendation is turned into an implicit vote.
    return rank_movies(movies, [], limit=len(movies)) if ranked else movies


def mutual(data):
    if len(data['members']) != 2:
        return []
    a, b = data['members']
    return [mid for mid in data['deck'] if a['votes'].get(mid) == b['votes'].get(mid) == 'yes']


def snapshot(sid, token):
    with db_session() as db:
        data = read(db, sid)
        me = member(data, token)
        # Terminal snapshots stay readable to members, so a second device can
        # explain why the room ended rather than losing the final result.
        phase = 'expired' if now().isoformat() >= data['expires_at'] else data['phase']
        movie_map = {m['id']: m for m in candidates(db, sid, data)}
        ids = [mid for mid in data['deck'] if mid in movie_map]
        votes = data['members'][me]['votes']
        matches = [movie_map[mid] for mid in mutual(data) if mid in movie_map]
        remaining = [movie_map[mid] for mid in ids if mid not in votes]
        return {'id': sid, 'room': data['room'], 'version': data['version'], 'phase': phase,
                'expires_at': data['expires_at'], 'filters': data['filters'], 'me': me,
                'people': [{'joined': True, 'ready': p['ready'], 'progress': len(p['votes'])} for p in data['members']],
                'total': len(ids), 'remaining': len(remaining), 'card': remaining[0] if remaining else None,
                'matches': matches, 'proposal': data['proposal'], 'confirmed': data['confirmed'],
                'final': movie_map.get(data['final']), 'saved': data['members'][me]['saved']}


def act(sid, token, action):
    with db_session() as db:
        db.execute('BEGIN IMMEDIATE')
        data = read(db, sid)
        me = member(data, token)
        available(data)
        person = data['members'][me]
        op, mid = action.op, action.movie_id
        # Old saved rooms have no watermarks. Require their current snapshot
        # once; persist the watermark before independent actions advance it.
        data.setdefault('conditions_version', data['version'])
        data.setdefault('proposal_version', data['version'])
        if action.version > data['version']:
            raise MatchError('Комната обновилась. Проверьте актуальные условия и повторите действие.')
        # An immutable vote per (session, browser, movie) makes retries and
        # multiple tabs safe without trusting a client-provided user id.
        duplicate = op == 'vote' and mid in person['votes']
        if duplicate:
            if person['votes'][mid] != action.vote:
                raise MatchError('Этот фильм уже оценён в другой вкладке. Обновите карточку.')
        elif op == 'vote':
            # An in-flight answer from this ballot can finish after the final
            # confirmation. Immutable votes cannot undo the two existing yes
            # votes on the final movie, and never reopen the decision.
            if data['phase'] not in {'voting', 'finished'} or mid not in data['deck'] or action.vote is None or action.version < data.get('ballot_version', 1):
                raise MatchError('Карточка устарела. Обновите выбор.')
            if mid not in {m['id'] for m in candidates(db, sid, data)}:
                raise MatchError('Фильм больше не проходит условия комнаты.')
            person['votes'][mid] = action.vote
            write(db, sid, data)
        else:
            # Consent belongs to the conditions/proposal the browser saw,
            # not to unrelated votes or the other person's consent. SQLite's
            # write lock serializes the merge; no stale state is overwritten.
            floor = (data['conditions_version'] if op == 'ready' else
                     data['proposal_version'] if op == 'confirm' else data['version'])
            if action.version < floor:
                raise MatchError('Комната обновилась. Проверьте актуальные условия и повторите действие.')
            if op == 'filters':
                if action.filters is None or data['phase'] not in {'lobby', 'voting'}:
                    raise MatchError('Сейчас нельзя менять условия.')
                filters = action.filters.model_dump()
                if filters == data['filters']:
                    return snapshot(sid, token)
                data['filters'] = filters
                data['conditions_version'] = data['version'] + 1
                data['phase'] = 'lobby'
                data['proposal'], data['confirmed'] = None, []
                for p in data['members']:
                    p['ready'] = False
            elif op == 'ready':
                if person['ready'] and data['phase'] in {'lobby', 'voting', 'finished'}:
                    return snapshot(sid, token)
                if data['phase'] != 'lobby' or len(data['members']) != 2:
                    raise MatchError('Дождитесь второго участника.')
                person['ready'] = True
                if all(p['ready'] for p in data['members']):
                    pool = [m['id'] for m in candidates(db, sid, data, ranked=True)]
                    if not pool:
                        raise MatchError('Подходящих фильмов нет. Согласуйте более широкие условия.')
                    data['deck'] = pool
                    data['phase'] = 'voting'
                    data['ballot_version'] = data['version'] + 1
            elif op == 'propose':
                if data['phase'] != 'voting' or mid not in mutual(data) or mid not in {m['id'] for m in candidates(db, sid, data)}:
                    raise MatchError('Выберите фильм из взаимных совпадений.')
                data['proposal'], data['confirmed'] = mid, [me]
                data['proposal_version'] = data['version'] + 1
            elif op == 'confirm':
                if data['phase'] == 'finished' and mid == data['final'] and me in data['confirmed']:
                    return snapshot(sid, token)
                if data['phase'] != 'voting' or mid != data['proposal'] or mid not in mutual(data) or mid not in {m['id'] for m in candidates(db, sid, data)}:
                    raise MatchError('Предложение изменилось. Проверьте фильм.')
                data['confirmed'] = sorted(set(data['confirmed'] + [me]))
                if len(data['confirmed']) == 2:
                    data['final'], data['phase'] = mid, 'finished'
                    db.execute("UPDATE sessions SET status='selected',selected_movie_id=? WHERE id=?", (mid, sid))
            elif op == 'cancel':
                if data['phase'] != 'voting':
                    raise MatchError('Выбор уже завершён.')
                data['proposal'], data['confirmed'] = None, []
            elif op in {'leave', 'close'}:
                data['phase'] = 'left' if op == 'leave' else 'closed'
                db.execute("UPDATE sessions SET status='abandoned' WHERE id=?", (sid,))
            elif op == 'save':
                if mid not in mutual(data):
                    raise MatchError('Сохранить можно фильм из совпадений.')
                person['saved'] = sorted(set(person['saved'] + [mid]))
            write(db, sid, data)
    return snapshot(sid, token)
