"""Natural-language discovery over the existing catalog, IQ and hard policies."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from backend.database.db import db_session, loads
from backend.movies.catalog import is_released, row_to_movie
from backend.movies.genres import normalize_genres
from backend.movies.search_query import THEMES, SearchCriteria, SmartSearchIn, conflicts, interpret, normalized, refine
from backend.recommendation.avoidance import load_avoidance_rules
from backend.recommendation.exclusions import active_evening, filter_movies, load_policy
from backend.recommendation.personal import WEIGHTS, features, rank_movies
from backend.recommendation.taste_profile import taste_signals


def title_key(value):
    return re.sub(r'[^\w]+', ' ', normalized(value or '')).strip()


def source_candidates(title: str, catalog: list[dict]) -> tuple[list[dict], bool]:
    """Exact duplicate titles require a choice; typo/partial hits are suggestions."""
    key = title_key(title)
    exact, partial, fuzzy = [], [], []
    for movie in catalog:
        aliases = {title_key(movie.get('title')), title_key(movie.get('original_title'))} - {''}
        if key in aliases:
            exact.append(movie)
        elif any(key in alias for alias in aliases) and len(key) >= 3:
            partial.append(movie)
        elif len(key) >= 4 and any(SequenceMatcher(None, key, alias).ratio() >= .78 for alias in aliases):
            fuzzy.append(movie)
    return (exact, True) if exact else ((partial or fuzzy)[:12], False)


def similarity(movie: dict, source: dict) -> tuple[float, list[str]]:
    left, right = features(movie), features(source)
    if not any(left[kind] & right[kind] for kind in WEIGHTS if kind != 'era'):
        return 0., []  # A shared decade alone cannot justify "similar".
    score, reasons = 0., []
    labels = {'genres': 'Общие жанры', 'keywords': 'Общие ключевые слова', 'director': 'Общий режиссёр',
              'cast_names': 'Общие актёры', 'era': 'Одна эпоха выпуска'}
    for kind, weight in WEIGHTS.items():
        overlap = left[kind] & right[kind]
        if overlap:
            score += weight * len(overlap) / len(left[kind] | right[kind])
            reasons.append(f'{labels[kind]}: {", ".join(sorted(overlap)[:3])}.')
    return score, reasons


def theme_evidence(movie: dict, theme: str) -> str | None:
    """Literal catalog evidence only. Twist themes require curated keywords."""
    label, _, terms = THEMES[theme]
    keywords = movie.get('keywords') or []
    for keyword in keywords:
        if any(_term_in(term, normalized(str(keyword))) for term in terms):
            return f'Тема «{label}»: ключевое слово «{keyword}» в каталоге.'
    if theme not in {'twists', 'light', 'tense', 'funny'}:
        overview = movie.get('overview') or ''
        for sentence in re.split(r'(?<=[.!?])\s+', overview):
            if any(_term_in(term, normalized(sentence)) for term in terms):
                # Include the actual evidence; never invent an atmosphere/ending.
                return f'Тема «{label}» упомянута в описании: «{sentence[:240]}».'
    return None


def _term_in(term, text):
    suffix = r'\w*' if re.search('[а-я]', term) else r's?'
    return bool(re.search(r'(?<!\w)' + re.escape(term) + suffix + r'(?!\w)', text))


def hard_checks(criteria: SearchCriteria, watched: set[str]):
    h = criteria.hard
    checks = []
    for genre in dict.fromkeys(h.genres):
        checks.append((f'Жанр: {genre}', lambda m, g=genre: g in (m.get('genres') or [])))
    for genre in dict.fromkeys(h.excluded_genres):
        checks.append((f'Без жанра: {genre} (неизвестные жанры исключены)',
                       lambda m, g=genre: bool(m.get('genres')) and g not in m['genres']))
    for field, value, is_min in (('runtime', h.min_runtime, True), ('runtime', h.max_runtime, False),
                                 ('year', h.min_year, True), ('year', h.max_year, False),
                                 ('rating', h.min_rating, True)):
        if value is not None:
            label = {'runtime': 'Длительность, мин', 'year': 'Год', 'rating': 'Рейтинг, из 10'}[field]
            checks.append((f'{label}: {"от" if is_min else "до"} {value}',
                           lambda m, f=field, v=value, low=is_min: m.get(f) is not None and
                           (m[f] > 0 if f in {'runtime', 'year'} else True) and (m[f] >= v if low else m[f] <= v)))
    if h.exclude_watched:
        checks.append(('Исключить просмотренное', lambda m: m['id'] not in watched))
    return checks


def search(user_id: str, payload: SmartSearchIn, limit: int = 12) -> dict:
    analysis = interpret(payload.query)
    criteria = (refine(payload.criteria, analysis) if payload.criteria and payload.refine else
                payload.criteria.model_copy(deep=True) if payload.criteria else analysis['criteria'])
    issues = conflicts(criteria)
    response = {'criteria': criteria.model_dump(), 'notes': list(analysis['notes']), 'unparsed': analysis['unparsed'],
                'conflicts': issues, 'items': [], 'sources': [], 'needs_source': False,
                'diagnostics': [], 'total': 0, 'catalog_count': 0, 'cold_start': True}
    if issues:
        return response
    has_hard = any(value is not None and value is not False and value != [] for value in criteria.hard.model_dump().values())
    has_soft = bool(criteria.soft.themes or criteria.soft.similar_title)
    if not has_hard and not has_soft:
        response['notes'].append('Укажите поддерживаемое условие: жанр, длительность, год, рейтинг, тему или фильм для похожего.')
        return response

    with db_session() as db:
        # Decode once, no poster filesystem probes until after ranking.
        rows = db.execute('SELECT * FROM movies').fetchall()
        catalog = [{**dict(r), 'genres': normalize_genres(loads(r['genres'], [])),
                    'keywords': loads(r['keywords'], []), 'cast_names': loads(r['cast_names'], [])} for r in rows]
        released = [m for m in catalog if is_released(m)]
        response['catalog_count'] = len(released)
        source = None
        if criteria.soft.similar_title:
            choices, exact = source_candidates(criteria.soft.similar_title, released)
            selected = next((m for m in choices if m['id'] == criteria.soft.source_id), None)
            source = selected or (choices[0] if len(choices) == 1 and exact and not criteria.soft.source_id else None)
            if not source:
                response['needs_source'] = True
                response['sources'] = [{'id': m['id'], 'title': m['title'], 'year': m['year'],
                                        'original_title': m['original_title']} for m in choices]
                response['notes'].append('Выберите исходный фильм.' if choices else 'Исходный фильм не найден в локальном каталоге. Уточните название.')
                return response
            criteria.soft.source_id = source['id']
            response['criteria'] = criteria.model_dump()
            response['source'] = {'id': source['id'], 'title': source['title'], 'year': source['year']}

        signals = taste_signals(db, user_id)
        avoidance = load_avoidance_rules(db, user_id)
        permanent, temporary, watched = load_policy(db, [user_id])
        evening = active_evening(db)
        prefs = db.execute('SELECT * FROM participants WHERE session_id=? AND user_id=?',
                           (evening['id'], user_id)).fetchone() if evening else None
        # Reuse active evening hard controls, but never its soft mood as a veto.
        saved = []
        if prefs:
            saved += [{'kind': 'genre', 'value': g} for g in normalize_genres(loads(prefs['disliked_genres'], []))]
            if prefs['max_runtime']:
                saved.append({'kind': 'max_runtime', 'value': str(prefs['max_runtime'])})
        base = released
        checks = hard_checks(criteria, watched)
        # All existing hard policies are evaluated after the explicit conditions.
        eligible = [m for m in base if all(check(m) for _, check in checks)]
        before_policy = len(eligible)
        eligible = filter_movies(eligible, permanent, temporary + saved, watched)
        if prefs and prefs['min_year']:
            eligible = [m for m in eligible if m.get('year') and m['year'] >= prefs['min_year']]
        # Match discovery's established treatment of explicit negative films;
        # negative genre evidence remains a soft IQ weight, never a genre veto.
        negative_ids = {s['movie_id'] for s in signals if s['value'] < 0} | {r['movie_id'] for r in avoidance}
        before_feedback = len(eligible)
        eligible = [m for m in eligible if m['id'] not in negative_ids]
        response['policies'] = {'permanent': len(permanent), 'temporary': len(temporary),
                                'evening': len(saved) + bool(prefs and prefs['min_year']),
                                'feedback_removed': before_feedback - len(eligible),
                                'removed': before_policy - len(eligible)}
        response['cold_start'] = not any(s['value'] != 0 for s in signals)
        # Personal ranking and avoid-similar penalties come from Tonight IQ.
        ranked = rank_movies(eligible, signals, rules=avoidance, limit=len(eligible), diversify=False)
        matches = []
        for movie in ranked:
            if source and movie['id'] == source['id']:
                continue
            evidence = [fact for theme in criteria.soft.themes if (fact := theme_evidence(movie, theme))]
            affinity, common = similarity(movie, source) if source else (0., [])
            if source and affinity <= 0:
                continue
            # Need at least one piece of query evidence, never a popularity fallback.
            # Themes remain soft relative to each other; not all must match.
            if criteria.soft.themes and not source and not evidence:
                continue
            facts = []
            if criteria.hard.genres:
                facts.append('Жанры: ' + ', '.join(criteria.hard.genres) + '.')
            if criteria.hard.excluded_genres:
                facts.append('В жанрах каталога нет: ' + ', '.join(criteria.hard.excluded_genres) + '.')
            if criteria.hard.min_runtime is not None or criteria.hard.max_runtime is not None:
                facts.append(f'Длительность: {movie["runtime"]} мин.')
            if criteria.hard.min_year is not None or criteria.hard.max_year is not None:
                facts.append(f'Год: {movie["year"]}.')
            if criteria.hard.min_rating is not None:
                facts.append(f'Рейтинг {"TMDB" if movie.get("tmdb_id") else "каталога (источник не указан)"}: {movie["rating"]}/10.')
            if criteria.hard.exclude_watched:
                facts.append('Нет отметки просмотра у выбранного зрителя.')
            facts += evidence
            if source:
                facts.append(f'Сходство с «{source["title"]}» по метаданным. ' + ' '.join(common))
            if len(evidence) < len(criteria.soft.themes):
                facts.append('Не все пожелания по темам подтверждены метаданными этого фильма.')
            movie['search_reasons'] = facts
            # Query evidence outranks the general taste profile. Deterministic ties.
            movie['_query_score'] = len(evidence) + affinity
            matches.append(movie)
        matches.sort(key=lambda m: (-m['_query_score'], -m['recommendation_score'], m['id']))
        response['total'] = len(matches)
        by_id = {r['id']: r for r in rows}
        saved_ids = {r[0] for r in db.execute('SELECT movie_id FROM watchlist')}
        response['items'] = [{**row_to_movie(by_id[m['id']]),
                              **{k: m[k] for k in ('search_reasons', 'recommendation_reason', 'personalized')},
                              'saved': m['id'] in saved_ids, 'rating_source': 'TMDB' if m.get('tmdb_id') else None} for m in matches[:limit]]
        if not matches:
            # One linear pass per active condition; report counts before policies,
            # not a promise to restore a movie blocked by another hard restriction.
            response['diagnostics'] = [{'label': label, 'excluded': sum(not check(m) for m in base)} for label, check in checks]
            response['diagnostics'] += [{'label': f'Тема по данным каталога: {THEMES[theme][0]}',
                                        'excluded': sum(not theme_evidence(m, theme) for m in base)}
                                       for theme in criteria.soft.themes]
            if before_policy - len(eligible):
                response['notes'].append('Сохранённые исключения или условия активного вечера также сократили подборку.')
                response['diagnostics'].append({'label': 'Сохранённые ограничения и явные отрицательные оценки (среди прошедших условия запроса)',
                                                 'excluded': before_policy - len(eligible)})
            if has_soft:
                response['notes'].append('Проверьте тему или исходный фильм: совпадение должно подтверждаться каталогом.')
    return response
