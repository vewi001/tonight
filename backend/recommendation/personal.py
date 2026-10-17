"""Deterministic personal discovery, using the existing Tonight IQ evidence.

No network calls, generated metadata, probabilities, or persisted taste vectors.
Popularity uses vote_count because this catalog has no popularity field.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import log1p
from pathlib import Path
from backend.movies.media import local_media
from typing import Any

from backend.database.db import db_session, loads
from backend.movies.catalog import _franchise_is_available, is_released, row_to_movie
from backend.movies.genres import normalize_genres
from backend.recommendation.avoidance import load_avoidance_rules, similarity_penalty
from backend.recommendation.engine import MOOD_GENRES
from backend.recommendation.taste_profile import taste_signals
from backend.recommendation.exclusions import load_policy, filter_movies, active_evening

WEIGHTS = {'genres': .32, 'keywords': .24, 'director': .14, 'cast_names': .10, 'era': .08}


def features(movie: dict) -> dict[str, set[str]]:
    def names(value):
        return {x.strip().casefold() for x in value if isinstance(x, str) and x.strip()} if isinstance(value, list) else set()
    year = movie.get('year')
    return {'genres': names(movie.get('genres')), 'keywords': names(movie.get('keywords')),
            'director': names([movie.get('director')]), 'cast_names': names(movie.get('cast_names')),
            'era': {str(year // 10 * 10)} if isinstance(year, int) and year > 1800 else set()}


def rank_movies(catalog: list[dict], signals: list[dict], *, excluded: set[str] | None = None,
                blocked_genres: set[str] | None = None, desired: set[str] | None = None,
                rules: list[dict] | None = None, exposure: dict[str, int] | None = None,
                min_year: int | None = None, max_runtime: int | None = None, limit: int = 6, diversify: bool = True) -> list[dict]:
    """Pure weighted ranking followed by a bounded greedy diversity pass."""
    points = {key: defaultdict(list) for key in WEIGHTS}
    for signal in signals:
        for kind, terms in features(signal).items():
            for term in terms:
                points[kind][term].append(signal['value'])
    # Shrink single observations toward neutral; repeated evidence strengthens it.
    profile = {kind: {term: sum(values) / (len(values) + 1) for term, values in terms.items()}
               for kind, terms in points.items()}
    ranked = []
    for movie in catalog:
        if movie['id'] in (excluded or set()) or set(movie.get('genres') or []) & (blocked_genres or set()):
            continue
        if min_year and (not movie.get('year') or movie['year'] < min_year):
            continue
        if max_runtime and (not movie.get('runtime') or movie['runtime'] > max_runtime):
            continue
        facts, terms = [], features(movie)
        contributions = {}
        for kind, weight in WEIGHTS.items():
            matches = [(term, profile[kind][term]) for term in terms[kind] if term in profile[kind]]
            contributions[kind] = weight * sum(value for _, value in matches) / max(1, len(terms[kind]))
            positives = sorted(term for term, value in matches if value > 0)
            if positives and contributions[kind] > 0:
                labels = {'genres': 'В положительных оценках встречается жанр', 'keywords': 'Тема из ваших положительных оценок',
                          'director': 'Режиссёр фильма из ваших положительных оценок', 'cast_names': 'Актёр из фильма, который вам понравился',
                          'era': 'Эпоха фильма из ваших положительных оценок'}
                term = positives[0]
                display = term
                if kind == 'director':
                    display = movie['director']
                elif kind == 'cast_names':
                    display = next(name for name in movie['cast_names'] if name.strip().casefold() == term)
                elif kind == 'era':
                    display = f'{term}-е'
                facts.append((contributions[kind], f"{labels[kind]}: {display}."))
        mood = bool(terms['genres'] & (desired or set()))
        personal = sum(contributions.values()) + (.12 if mood else 0)
        if mood:
            facts.append((.12, 'Жанр подходит под выбранное вами настроение.'))
        rating = max(0., min(10., movie.get('rating') or 0))
        votes = max(0, movie.get('vote_count') or 0)
        quality = (rating / 10) * votes / (votes + 100)
        popularity = min(1., log1p(votes) / log1p(100000))
        penalty = similarity_penalty(movie, rules or [])
        score = personal + .09 * quality + .03 * popularity - penalty - min(.30, .10 * (exposure or {}).get(movie['id'], 0))
        personalized = personal > 0 and bool(facts) and personal > penalty
        if personalized:
            reason = max(facts)[1]
        elif rating >= 7 and votes >= 100:
            reason = f'Стартовый вариант: зрительский рейтинг {rating:.1f} из 10; личного совпадения пока нет.'
        else:
            reason = 'Вариант для знакомства: пока недостаточно данных для личного совпадения.'
        ranked.append({**movie, 'recommendation_score': round(score, 6), 'personalized': personalized,
                       'recommendation_reason': reason, 'ranking_factors': contributions})
    if not diversify:
        return sorted(ranked, key=lambda m: (-m['recommendation_score'], m['id']))[:limit]
    # Limit the quadratic reranking to a small pool. Deterministic ties use ID.
    pool = sorted(ranked, key=lambda m: (-m['recommendation_score'], m['id']))[:max(120, limit * 10)]
    chosen, genre_counts, franchises = [], defaultdict(int), set()
    while pool and len(chosen) < max(0, limit):
        def adjusted(movie):
            genres = set(movie.get('genres') or [])
            concentration = max((genre_counts[g] for g in genres), default=0)
            franchise = movie.get('franchise_key')
            return movie['recommendation_score'] - .16 * concentration - (.22 if franchise and franchise in franchises else 0)
        best = min(pool, key=lambda m: (-adjusted(m), m['id']))
        pool.remove(best)
        chosen.append(best)
        for genre in set(best.get('genres') or []):
            genre_counts[genre] += 1
        if best.get('franchise_key'):
            franchises.add(best['franchise_key'])
    return chosen


def personal_recommendations(user_id: str, limit: int = 6, reference_day: date | None = None, *, tonight: dict | None = None, tinder_seen: list[str] | None = None, roulette: dict | None = None) -> dict[str, Any]:
    day = reference_day or date.today()
    with db_session() as db:
        signals = taste_signals(db, user_id)
        rules = load_avoidance_rules(db, user_id)
        if tonight and tonight['company'] == 'couple':
            other = 'nikita' if user_id == 'lera' else 'lera'
            signals += taste_signals(db, other)
            rules += load_avoidance_rules(db, other)
        watched_users = ['lera', 'nikita'] if tonight and tonight['company'] == 'couple' else [user_id]
        watched = {row[0] for row in db.execute(
            "SELECT h.movie_id FROM watch_history h JOIN sessions s ON s.id=h.session_id WHERE s.viewing_company!='solo' OR s.solo_user_id IN (" + ','.join('?' for _ in watched_users) + ')', watched_users)}
        marks = defaultdict(set)
        for row in db.execute('SELECT movie_id,action FROM viewer_movie_actions WHERE user_id=?', (user_id,)):
            marks[row['movie_id']].add(row['action'])
        companion_marks = list(db.execute('SELECT movie_id,action FROM viewer_movie_actions WHERE user_id=?', (other,))) if tonight and tonight['company'] == 'couple' else []
        watched |= {r['movie_id'] for r in companion_marks if r['action'] == 'watched'}
        watched |= {mid for mid, action in marks.items() if 'watched' in action}
        excluded = (watched if tonight is None or tonight['exclude_watched'] else set()) | {mid for mid, action in marks.items() if 'dislike' in action} | {r['movie_id'] for r in rules}
        excluded.update(r['movie_id'] for r in companion_marks if r['action'] == 'dislike')
        excluded.update(s['movie_id'] for s in signals if s['value'] < 0)
        if tinder_seen is not None:
            excluded.update(tinder_seen)
            excluded.update(r[0] for r in db.execute('SELECT DISTINCT movie_id FROM tinder_actions WHERE user_id=? AND undone=0', (user_id,)))
        for row in db.execute('SELECT rejected_movies,selected_movie_id,status FROM sessions'):
            excluded.update(loads(row['rejected_movies'], []))
            if row['status'] in {'selected', 'watching'}:
                excluded.add(row['selected_movie_id'])
        evening = active_evening(db)
        prefs = db.execute('SELECT * FROM participants WHERE user_id=? AND session_id=?', (user_id, evening['id'])).fetchone() if evening else None
        blocked = set(loads(prefs['disliked_genres'], [])) if prefs else set()
        desired = set().union(*(MOOD_GENRES.get(mood, set()) for mood in loads(prefs['moods'], []))) if prefs else set()
        # Today's batch is stable; previous days rotate deterministically.
        exposure = {row['movie_id']: row['n'] for row in db.execute(
            'SELECT movie_id,COUNT(*) n FROM personal_impressions WHERE user_id=? AND day>=? AND day<? GROUP BY movie_id',
            (user_id, (day - timedelta(days=7)).isoformat(), day.isoformat()))}
        for row in db.execute('''SELECT s.recommendations FROM sessions s
                JOIN participants p ON p.session_id=s.id WHERE p.user_id=?
                AND substr(s.updated_at,1,10)>=? AND substr(s.updated_at,1,10)<?''',
                (user_id, (day - timedelta(days=7)).isoformat(), day.isoformat())):
            for item in loads(row['recommendations'], []):
                if isinstance(item, dict) and item.get('id'):
                    exposure[item['id']] = exposure.get(item['id'], 0) + 1
        rows = db.execute('SELECT * FROM movies').fetchall()
        # Do not resolve image files for the whole catalog on each request.
        catalog = [{**dict(row), 'genres': normalize_genres(loads(row['genres'], [])),
                    'keywords': loads(row['keywords'], []), 'cast_names': loads(row['cast_names'], [])} for row in rows]
        franchise_catalog = defaultdict(list)
        for movie in catalog:
            if movie.get('franchise_key'):
                franchise_catalog[movie['franchise_key']].append(movie)
        eligible = [m for m in catalog if is_released(m, day) and
                    _franchise_is_available(m, watched, franchise_catalog.get(m.get('franchise_key'), []))]
        policy_users = watched_users
        permanent, temporary, policy_watched = load_policy(db, policy_users)
        before_policies = len(eligible)
        eligible = filter_movies(eligible, permanent, temporary, policy_watched)
        exclusion_diagnostics = {'permanent': len(permanent), 'temporary': len(temporary),
                                 'removed': before_policies - len(eligible)}
        diagnostics = []
        catalog_available = before_policies
        if tonight is not None:
            excluded.update(tonight['seen_ids'])
            blocked = (blocked if roulette is not None else set()) | set(tonight['excluded_genres'])
            desired = desired if roulette is not None else MOOD_GENRES.get(tonight['mood'], set())
            checks = [
                ('mood', 'настроение', lambda m: roulette is not None or not desired or bool(set(m['genres']) & desired)),
                ('company', 'семейный жанр', lambda m: tonight['company'] != 'family' or bool(set(m['genres']) & {'семейный','мультфильм'}) and not set(m['genres']) & {'хоррор','триллер'}),
            ]
            from backend.recommendation.constraints import condition_checks
            checks += condition_checks(tonight, blocked)
            base = [m for m in eligible if m['id'] not in excluded]
            eligible = [m for m in base if all(check(m) for _, _, check in checks)]
            if len(eligible) < limit:
                for key, label, check in checks:
                    count = sum(all(other(m) for otherkey, _, other in checks if otherkey != key) for m in base)
                    if count > len(eligible):
                        diagnostics.append({'field': key, 'label': label, 'available': count})
        watchlist_count = None
        if roulette is not None:
            # Intersect quick controls with the existing saved hard preferences.
            if prefs:
                eligible = [m for m in eligible if
                            (not prefs['min_year'] or m.get('year') and m['year'] >= prefs['min_year']) and
                            (not prefs['max_runtime'] or m.get('runtime') and m['runtime'] <= prefs['max_runtime'])]
            wanted = set(roulette['included_genres'])
            eligible = [m for m in eligible if not wanted or set(m['genres']) & wanted]
            if roulette['mode'] == 'watchlist':
                saved_ids = {r[0] for r in db.execute('SELECT movie_id FROM watchlist')}
                watchlist_count = len(saved_ids)
                eligible = [m for m in eligible if m['id'] in saved_ids]
        items = rank_movies(eligible, signals, excluded=excluded, blocked_genres=blocked, desired=desired,
                            rules=rules, exposure=exposure, min_year=prefs['min_year'] if prefs and tonight is None else None,
                            max_runtime=prefs['max_runtime'] if prefs and tonight is None else None, limit=len(eligible) if roulette is not None else limit, diversify=roulette is None)
        candidate_count = len(items)
        if roulette is not None and items:
            from backend.recommendation.roulette import weighted_pick
            items = [weighted_pick(items, roulette['mode'])]
        by_id = {row['id']: row for row in rows}
        items = [{**row_to_movie(by_id[item['id']]), **{key: item[key] for key in
                  ('recommendation_score', 'personalized', 'recommendation_reason', 'ranking_factors')}} for item in items]
        for item in items:
            poster_path = by_id[item['id']]['poster_path']
            item['poster_available'] = bool((poster_path and Path(poster_path).is_file()) or local_media(item['id'], 'poster'))
            item['rating_source'] = 'TMDB' if item.get('tmdb_id') else None
            item['viewer_actions'] = sorted(marks.get(item['id'], set()))
            item['saved'] = bool(db.execute('SELECT 1 FROM watchlist WHERE movie_id=?', (item['id'],)).fetchone())
        db.execute('DELETE FROM personal_impressions WHERE day<?', ((day - timedelta(days=7)).isoformat(),))
        db.executemany('INSERT OR IGNORE INTO personal_impressions(user_id,movie_id,day) VALUES(?,?,?)',
                       [(user_id, m['id'], day.isoformat()) for m in items])
    return {'items': items, 'candidate_count': candidate_count, 'watchlist_count': watchlist_count, 'cold_start': not any(s['value'] for s in signals) and (tonight is not None or not desired),
            'exclusions': exclusion_diagnostics, 'limited': len(items) < limit, 'relaxations': diagnostics, 'catalog_available': catalog_available,
            'exhausted': bool(tonight and tonight['seen_ids'] and len(items) < limit)}
