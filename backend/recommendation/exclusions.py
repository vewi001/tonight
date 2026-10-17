"""Hard discovery policies, separate from IQ evidence and similarity penalties.

Temporary rules belong to an existing evening, expire at its end or midnight,
and are never read by taste_signals. Catalog lookup remains unrestricted.
"""
from datetime import date, datetime

from backend.database.db import db_session, dumps, loads
from backend.movies.genres import canonical_genre, normalize_genres

KINDS = {'movie', 'genre', 'keyword', 'director', 'max_runtime', 'watched'}
USERS = ('lera', 'nikita')


def active_evening(db, session_id=None, today=None):
    day = (today or date.today()).isoformat()
    if session_id is None:
        row = db.execute("SELECT * FROM sessions WHERE session_date=? AND match_data='{}' ORDER BY id DESC LIMIT 1", (day,)).fetchone()
    else:
        row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    return row if row and row['session_date'] == day and row['status'] not in {'completed', 'abandoned'} else None


def watched_ids(db, users):
    ids = {r['movie_id'] for r in db.execute('''SELECT h.movie_id,s.viewing_company,s.solo_user_id
        FROM watch_history h JOIN sessions s ON s.id=h.session_id''')
        if r['viewing_company'] != 'solo' or r['solo_user_id'] in users}
    ids.update(r['movie_id'] for r in db.execute("SELECT user_id,movie_id FROM viewer_movie_actions WHERE action='watched'") if r['user_id'] in users)
    return ids


def load_policy(db, users, session_id=None):
    permanent = [dict(r) for r in db.execute('SELECT user_id,kind,value FROM recommendation_exclusions') if r['user_id'] in users]
    # Preserve the established meaning of explicit disinterest, including old data.
    permanent += [{'user_id': r['user_id'], 'kind': 'movie', 'value': r['movie_id']}
                  for r in db.execute("SELECT user_id,movie_id FROM viewer_movie_actions WHERE action='dislike'") if r['user_id'] in users]
    evening = active_evening(db, session_id)
    temporary = []
    if evening:
        data = loads(evening['temporary_exclusions'], {})
        for user in users:
            temporary.extend(data.get(user, []))
    return permanent, temporary, watched_ids(db, users)


def allows(movie, rules, watched=()):
    """Unknown mandatory metadata fails closed, rather than guessing a match."""
    for rule in rules:
        kind, value = rule['kind'], rule['value']
        if kind == 'movie' and movie['id'] == value:
            return False
        if kind in {'genre', 'keyword'}:
            terms = movie.get('genres' if kind == 'genre' else 'keywords') or []
            if isinstance(terms, str):
                terms = loads(terms, [])
            terms = normalize_genres(terms) if kind == 'genre' else terms
            if not terms or value.casefold() in {str(t).strip().casefold() for t in terms}:
                return False
        if kind == 'director' and (not movie.get('director') or movie['director'].strip().casefold() == value.casefold()):
            return False
        if kind == 'max_runtime' and (not movie.get('runtime') or movie['runtime'] > int(value)):
            return False
        if kind == 'watched' and movie['id'] in watched:
            return False
    return True


def filter_movies(movies, permanent, temporary=(), watched=()):
    return [m for m in movies if allows(m, permanent, watched) and allows(m, temporary, watched)]


def filter_for_users(db, movies, users=USERS, session_id=None):
    permanent, temporary, watched = load_policy(db, users, session_id)
    return filter_movies(movies, permanent, temporary, watched)


def options(db):
    rows = db.execute('SELECT genres,keywords,director FROM movies').fetchall()
    return {
        'genre': sorted({g for r in rows for g in normalize_genres(loads(r['genres'], []))}),
        'keyword': sorted({str(k).strip() for r in rows for k in loads(r['keywords'], []) if isinstance(k, str) and k.strip()}),
        'director': sorted({r['director'].strip() for r in rows if r['director'] and r['director'].strip()}),
    }


def validate_rule(db, kind, value):
    if kind not in KINDS:
        raise ValueError('Неизвестный вид исключения')
    value = str(value).strip()
    if kind == 'genre':
        value = canonical_genre(value) or ''
    if kind in {'genre', 'keyword', 'director'}:
        value = next((v for v in options(db)[kind] if v.casefold() == value.casefold()), '')
        if not value:
            raise ValueError('Этой характеристики нет в каталоге')
    elif kind == 'movie':
        if not db.execute('SELECT 1 FROM movies WHERE id=?', (value,)).fetchone():
            raise ValueError('Фильм не найден')
    elif kind == 'max_runtime':
        if not value.isdecimal() or not 1 <= int(value) <= 1440:
            raise ValueError('Укажите длительность от 1 до 1440 минут')
        value = str(int(value))
    elif kind == 'watched':
        if value != 'true':
            raise ValueError('Неверное ограничение просмотренного')
    return {'kind': kind, 'value': value}


def change_rule(user, scope, *, kind=None, value=None, session_id=None, remove=False, clear=False):
    if user not in USERS or scope not in {'permanent', 'temporary'}:
        raise ValueError('Неизвестный пользователь или контекст')
    with db_session() as db:
        db.execute('BEGIN IMMEDIATE')
        if scope == 'permanent':
            if clear:
                db.execute('DELETE FROM recommendation_exclusions WHERE user_id=?', (user,))
            elif remove:
                db.execute('DELETE FROM recommendation_exclusions WHERE user_id=? AND kind=? AND value=?', (user, kind, value))
            else:
                rule = validate_rule(db, kind, value)
                count = db.execute('SELECT COUNT(*) FROM recommendation_exclusions WHERE user_id=?', (user,)).fetchone()[0]
                if count >= 200:
                    raise ValueError('Достигнут предел: 200 постоянных исключений')
                if rule['kind'] == 'max_runtime':
                    db.execute("DELETE FROM recommendation_exclusions WHERE user_id=? AND kind='max_runtime'", (user,))
                db.execute('INSERT OR IGNORE INTO recommendation_exclusions VALUES(?,?,?,?)',
                           (user, rule['kind'], rule['value'], datetime.now().isoformat()))
        else:
            evening = active_evening(db, session_id)
            if not evening:
                raise ValueError('Этот вечер завершён. Начните новый подбор.')
            data = loads(evening['temporary_exclusions'], {})
            current = data.get(user, [])
            if clear:
                current = []
            elif remove:
                current = [r for r in current if (r['kind'], r['value']) != (kind, value)]
            else:
                rule = validate_rule(db, kind, value)
                if rule not in current:
                    if len(current) >= 100:
                        raise ValueError('Достигнут предел: 100 ограничений вечера')
                    if rule['kind'] == 'max_runtime':
                        current = [r for r in current if r['kind'] != 'max_runtime']
                    current.append(rule)
            data[user] = current
            db.execute('UPDATE sessions SET temporary_exclusions=? WHERE id=?', (dumps(data), evening['id']))


def state_for_user(user, session_id=None):
    with db_session() as db:
        permanent = [dict(r) for r in db.execute('SELECT kind,value FROM recommendation_exclusions WHERE user_id=? ORDER BY kind,value', (user,))]
        for rule in permanent:
            if rule['kind'] == 'movie':
                row = db.execute('SELECT title FROM movies WHERE id=?', (rule['value'],)).fetchone()
                rule['title'] = row['title'] if row else rule['value']
        evening = active_evening(db, session_id)
        temporary = loads(evening['temporary_exclusions'], {}).get(user, []) if evening else []
        for rule in temporary:
            if rule['kind'] == 'movie':
                row = db.execute('SELECT title FROM movies WHERE id=?', (rule['value'],)).fetchone()
                rule['title'] = row['title'] if row else rule['value']
        disinterest = [dict(r) for r in db.execute("SELECT a.movie_id,m.title FROM viewer_movie_actions a JOIN movies m ON m.id=a.movie_id WHERE a.user_id=? AND a.action='dislike' ORDER BY a.created_at DESC", (user,))]
        return {'disinterest': disinterest, 'user': user, 'permanent': permanent, 'temporary': temporary,
                'session_id': evening['id'] if evening else None, 'expires': evening['session_date'] if evening else None,
                'options': options(db)}
