"""Transactional discovery actions; preferences live in viewer_movie_actions."""
from datetime import datetime
from backend.database.db import db_session, dumps, loads


class ActionConflict(ValueError):
    pass


def snapshot(db, user, movie, with_watchlist):
    result = {'marks': [dict(r) for r in db.execute(
        'SELECT * FROM viewer_movie_actions WHERE user_id=? AND movie_id=? ORDER BY action', (user, movie))]}
    if with_watchlist:
        row = db.execute('SELECT * FROM watchlist WHERE movie_id=?', (movie,)).fetchone()
        result['watchlist'] = dict(row) if row else None
    return result


def act(user, movie, action, request_id, save=False):
    with db_session() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM tinder_actions WHERE id=?', (request_id,)).fetchone()
        if old:
            if old['user_id'] != user or old['movie_id'] != movie or old['action'] != action or old['undone'] or ('watchlist' in loads(old['after_state'], {})) != save:
                raise ActionConflict('Это действие уже изменено. Обновите подборку.')
            return {'id': request_id, 'action': action}
        if not db.execute('SELECT 1 FROM movies WHERE id=?', (movie,)).fetchone():
            raise LookupError('Фильм не найден')
        before = snapshot(db, user, movie, save)
        now = datetime.now().isoformat()
        if action in {'interest', 'dislike'}:
            db.execute("DELETE FROM viewer_movie_actions WHERE user_id=? AND movie_id=? AND action IN ('interest','dislike')", (user, movie))
        db.execute('INSERT OR REPLACE INTO viewer_movie_actions VALUES(?,?,?,?)', (user, movie, action, now))
        if save:
            db.execute('INSERT OR IGNORE INTO watchlist(movie_id,saved_at,saved_by) VALUES(?,?,?)', (movie, now, user))
        after = snapshot(db, user, movie, save)
        db.execute('INSERT INTO tinder_actions VALUES(?,?,?,?,?,?,0,?)', (request_id,user,movie,action,dumps(before),dumps(after),now))
    return {'id': request_id, 'action': action}


def undo(user, request_id):
    with db_session() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM tinder_actions WHERE id=? AND user_id=?', (request_id,user)).fetchone()
        if not row:
            raise LookupError('Действие не найдено')
        if row['undone']:
            return {'ok': True, 'movie_id': row['movie_id']}
        latest = db.execute('SELECT id FROM tinder_actions WHERE user_id=? AND undone=0 ORDER BY rowid DESC LIMIT 1', (user,)).fetchone()
        if latest['id'] != request_id:
            raise ActionConflict('Сначала отмените последнее действие.')
        before, after = loads(row['before_state'], {}), loads(row['after_state'], {})
        movie = row['movie_id']
        if snapshot(db,user,movie,'watchlist' in after) != after:
            raise ActionConflict('Данные фильма изменились на другом экране. Отмена не перезапишет эти изменения.')
        db.execute('DELETE FROM viewer_movie_actions WHERE user_id=? AND movie_id=?', (user,movie))
        for mark in before['marks']:
            db.execute('INSERT INTO viewer_movie_actions VALUES(?,?,?,?)', (user,movie,mark['action'],mark['created_at']))
        if 'watchlist' in before and before['watchlist'] != after['watchlist']:
            db.execute('DELETE FROM watchlist WHERE movie_id=?', (movie,))
            old = before['watchlist']
            if old:
                db.execute('INSERT INTO watchlist(movie_id,saved_at,saved_by,deferred_reason) VALUES(?,?,?,?)',
                           (movie,old['saved_at'],old['saved_by'],old['deferred_reason']))
        db.execute('UPDATE tinder_actions SET undone=1 WHERE id=?', (request_id,))
    return {'ok': True, 'movie_id': movie}
