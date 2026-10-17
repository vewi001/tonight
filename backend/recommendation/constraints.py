"""Common strict catalog conditions for Tonight's selection modes."""

def condition_checks(conditions, blocked=None):
    f = conditions
    excluded = set(f.get('excluded_genres', [])) if blocked is None else blocked
    return [
        ('max_runtime', 'продолжительность (фильмы без длительности тоже исключены)', lambda m: not f['max_runtime'] or bool(m.get('runtime') and m['runtime'] <= f['max_runtime'])),
        ('min_rating', 'минимальный рейтинг (без оценки фильмы исключены)', lambda m: not f['min_rating'] or bool(m.get('rating') is not None and m['rating'] >= f['min_rating'])),
        ('year', 'диапазон лет', lambda m: bool(m.get('year')) and (not f['min_year'] or m['year'] >= f['min_year']) and (not f['max_year'] or m['year'] <= f['max_year'])),
        ('excluded_genres', 'исключённые жанры', lambda m: not set(m['genres']) & excluded),
    ]


def meets_conditions(movie, conditions):
    wanted = set(conditions.get('included_genres', []))
    return all(check(movie) for _, _, check in condition_checks(conditions)) and (not wanted or bool(set(movie['genres']) & wanted))
