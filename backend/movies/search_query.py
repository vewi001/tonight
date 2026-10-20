"""Bounded, deterministic Russian query interpretation. No movie facts are inferred.

Only this small grammar is cached; catalog data and personal results are always fresh.
Consumed spans leave an honest remainder, including unsupported negations.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GENRES = ('хоррор', 'романтика', 'комедия', 'драма', 'боевик', 'sci-fi',
          'фэнтези', 'детектив', 'триллер', 'мультфильм', 'мюзикл', 'документальное',
          'приключения', 'криминал', 'семейный', 'история', 'музыка', 'военный', 'вестерн')
Genre = Literal[GENRES]
Theme = Literal['space', 'time', 'robots', 'friendship', 'love', 'twists', 'light', 'tense', 'funny']
THEMES = {
    'space': ('космос', r'космос\w*|космическ\w*', ('космос', 'космическ', 'space', 'astronaut', 'spacecraft')),
    'time': ('путешествия во времени', r'путешеств\w* во времени', ('путешествия во времени', 'time travel')),
    'robots': ('роботы', r'робот\w*', ('робот', 'robot', 'android')),
    'friendship': ('дружба', r'дружб\w*', ('дружб', 'friendship')),
    'love': ('любовь', r'любов\w*', ('любов', 'love story')),
    'twists': ('неожиданные повороты', r'(?:неожиданн\w* |сюжетн\w* )поворот\w*', ('plot twist', 'twist ending', 'twist', 'неожиданные повороты', 'твист')),
    'light': ('лёгкое настроение (по тегам)', r'легк\w*|уютн\w*', ('легкое', 'уют', 'feel-good', 'feelgood', 'light-hearted', 'lighthearted')),
    'tense': ('напряжение (по тегам)', r'напряженн\w*', ('напряжение', 'саспенс', 'suspense', 'suspenseful')),
    'funny': ('юмор (по тегам)', r'весел\w*|смешн\w*', ('юмор', 'humor', 'humour', 'comedy')),
}
GENRE_PATTERNS = {
    'хоррор': r'ужас\w*|хоррор\w*|horror',
    'романтика': r'романтик\w*|романтическ\w*|мелодрам\w*|romance',
    'комедия': r'комеди\w*|comedy', 'драма': r'драм[ауыойе]|драматическ\w*|drama',
    'боевик': r'боевик\w*|экшен\w*|action',
    'sci-fi': r'(?:научн\w* )?фантастик\w*|sci-fi|science fiction',
    'фэнтези': r'фэнтези|фентези|fantasy', 'детектив': r'детектив\w*|mystery',
    'триллер': r'триллер\w*|thriller', 'мультфильм': r'мультфильм\w*|мультик\w*|анимаци\w*|animation',
    'мюзикл': r'мюзикл\w*', 'документальное': r'документальн\w*|documentary',
    'приключения': r'приключени\w*|приключенческ\w*|adventure',
    'криминал': r'криминал\w*|crime', 'семейный': r'семейн\w*|family',
    'история': r'историческ\w*|history', 'музыка': r'музыкальн\w*|music',
    'военный': r'военн\w*|war', 'вестерн': r'вестерн\w*|western',
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class HardCriteria(StrictModel):
    genres: list[Genre] = Field(default_factory=list, max_length=20)
    excluded_genres: list[Genre] = Field(default_factory=list, max_length=20)
    min_runtime: int | None = Field(None, ge=1, le=1440)
    max_runtime: int | None = Field(None, ge=1, le=1440)
    min_year: int | None = Field(None, ge=1888, le=2100)
    max_year: int | None = Field(None, ge=1888, le=2100)
    min_rating: float | None = Field(None, ge=0, le=10)
    exclude_watched: bool = False


class SoftCriteria(StrictModel):
    themes: list[Theme] = Field(default_factory=list, max_length=9)
    similar_title: str | None = Field(None, max_length=200)
    source_id: str | None = Field(None, max_length=200)


class SearchCriteria(StrictModel):
    hard: HardCriteria = Field(default_factory=HardCriteria)
    soft: SoftCriteria = Field(default_factory=SoftCriteria)


class SmartSearchIn(StrictModel):
    query: str = Field(default='', max_length=500)
    criteria: SearchCriteria | None = None
    refine: bool = False
    offset: int = Field(0, ge=0, le=100000)


def normalized(text: str) -> str:
    return re.sub(r'\s+', ' ', text.casefold().replace('ё', 'е')).strip()


def _coordinated_negation(prefix: str) -> bool:
    """Carry a negative list through unknown traits, with bounded token work.

    Avoid ambiguous nested regex repetitions over arbitrary user text.
    """
    tokens = re.findall(r'[\w-]+|[,;.!?]', prefix)
    for i in range(len(tokens) - 1, -1, -1):
        token = tokens[i]
        if token in {'но', 'а', 'зато', ';', '.', '!', '?'}:
            return False
        if token in {'без', 'кроме'} or token.startswith('исключи'):
            tail = tokens[i+1:]
            return not tail or tail[-1] in {'и', 'или', ','}
    return False


def conflicts(criteria: SearchCriteria) -> list[str]:
    h = criteria.hard
    result = []
    if set(h.genres) & set(h.excluded_genres):
        result.append('Один жанр одновременно указан и исключён.')
    for low, high, label in ((h.min_year, h.max_year, 'лет'), (h.min_runtime, h.max_runtime, 'длительности')):
        if low is not None and high is not None and low > high:
            result.append(f'Начало диапазона {label} больше конца.')
    return result


def interpret(text: str) -> dict:
    # Return fresh mutable models even for a cache hit.
    parsed = _interpret(text)
    return parsed.copy() | {'criteria': SearchCriteria.model_validate_json(parsed['criteria_json'])}


@lru_cache(maxsize=256)
def _interpret(text: str) -> dict:
    if len(text) > 500:
        raise ValueError('Запрос не должен быть длиннее 500 символов.')
    text = normalized(text)
    consumed = [False] * len(text)
    criteria = SearchCriteria()
    hard, soft = criteria.hard, criteria.soft
    notes, touched = [], set()

    def take(start, end):
        consumed[start:end] = [True] * (end - start)

    def matches(pattern):
        # Cyrillic-aware boundaries (Python's \w), unlike JS-style \b usage.
        return list(re.finditer(r'(?<!\w)(?:' + pattern + r')(?!\w)', text))

    def free(match):
        return not any(consumed[match.start():match.end()])

    def set_h(field, value, *, lower=False):
        old = getattr(hard, field)
        # Multiple conditions are intersected, never silently relaxed.
        setattr(hard, field, (max(old, value) if lower else min(old, value)) if old is not None else value)
        touched.add(field)

    # Capture the reference before looking for genres/numbers inside its title.
    similar = re.search(r'(?<!\w)(?:похож\w* на|как(?: в)? фильм(?:е)?|как)\s+(?:фильм\s+)?(.+?)(?=,|;|\s+(?:но|только|без|до|после|не больше)\s|$)', text)
    if similar:
        title = similar.group(1).strip(' «»".!?')
        if title:
            soft.similar_title = title[:200]
            touched.add('similar_title')
            take(similar.start(), similar.end())

    number = r'\d+(?:[.,]\d+)?|полтора|полторы|один|одного|одной|одну|два|двух|две|три|трех|четыре|четырех'
    numbers = {'полтора': 1.5, 'полторы': 1.5, 'один': 1, 'одного': 1, 'одной': 1, 'одну': 1,
               'два': 2, 'двух': 2, 'две': 2, 'три': 3, 'трех': 3, 'четыре': 4, 'четырех': 4}
    for m in matches(r'(?:от\s+)?(\d+)\s*(?:[-–]|до)\s*(\d+)\s*(минут\w*|мин|час\w*)'):
        if free(m):
            low, high = (int(m.group(i)) * (60 if m.group(3).startswith('час') else 1) for i in (1, 2))
            if 1 <= low <= 1440 and 1 <= high <= 1440:
                set_h('min_runtime', low, lower=True)
                set_h('max_runtime', high)
                take(m.start(), m.end())
    duration = rf'(?:(не больше|не более|не дольше|не длиннее|до|максимум|короче|не меньше|не менее|от|дольше|больше)\s+)?({number})\s*(час\w*|минут\w*|мин)(?:\s+(?:и\s+)?(\d+)\s*(?:минут\w*|мин))?'
    for m in matches(duration):
        if not free(m):
            continue
        op, amount, unit, minutes = m.groups()
        value = numbers.get(amount)
        value = float(amount.replace(',', '.')) if value is None else value
        value = round(value * (60 if unit.startswith('час') else 1) + int(minutes or 0))
        if not 1 <= value <= 1440:
            notes.append('Длительность должна быть от 1 до 1440 минут.')
        else:
            low = op in {'не меньше', 'не менее', 'от', 'дольше', 'больше'}
            bound = value + (1 if op in {'дольше', 'больше'} else -1 if op == 'короче' else 0)
            if 1 <= bound <= 1440:
                set_h('min_runtime' if low else 'max_runtime', bound, lower=low)
            else:
                notes.append('Указанное условие длительности выходит за поддерживаемый диапазон 1–1440 минут.')
        take(m.start(), m.end())

    for m in matches(r'(?:с|от)\s+(\d{4})\s*(?:года?\s*)?(?:по|до|[-–])\s*(\d{4})(?:\s*года?)?|(\d{4})\s*[-–]\s*(\d{4})(?:\s*год\w*)?'):
        if free(m):
            a, b, c, d = m.groups()
            if 1888 <= int(a or c) <= 2100 and 1888 <= int(b or d) <= 2100:
                set_h('min_year', int(a or c), lower=True)
                set_h('max_year', int(b or d))
                take(m.start(), m.end())
    for m in matches(r'(не старше|не раньше|не ранее|не позже|не позднее|после|новее|позже|до|раньше|старше|с|от|по|в)\s+(\d{4})(?:\s*год\w*)?'):
        if free(m):
            op, year = m.group(1), int(m.group(2))
            if 1888 <= year <= 2100:
                if op == 'в':
                    set_h('min_year', year, lower=True)
                    set_h('max_year', year)
                elif op in {'не старше', 'не раньше', 'не ранее', 'с', 'от', 'после', 'новее', 'позже'}:
                    set_h('min_year', year + (op in {'после', 'новее', 'позже'}), lower=True)
                else:
                    set_h('max_year', year - (op in {'до', 'раньше', 'старше'}))
                take(m.start(), m.end())

    for m in matches(r'(?:с\s+)?рейтинг\w*\s*(?:не ниже|не меньше|от|выше|больше|>=|≥)?\s*(\d+(?:[.,]\d+)?)(?:\s*(?:из 10|\+))?'):
        if free(m):
            rating = float(m.group(1).replace(',', '.'))
            if 0 <= rating <= 10:
                set_h('min_rating', rating, lower=True)
                notes.append('Порог рейтинга включительный, по шкале 0–10. Источник указан в карточке, если известен.')
            else:
                notes.append('Рейтинг TMDB должен быть от 0 до 10.')
            take(m.start(), m.end())
    for m in matches(r'(?:с\s+)?(?:хорош\w*|высок\w*) рейтинг\w*'):
        if free(m):
            set_h('min_rating', 7.0, lower=True)
            notes.append('Для «хорошего рейтинга» порог по умолчанию — 7/10; его можно изменить.')
            take(m.start(), m.end())

    for m in matches(r'(?:котор\w*\s+)?(?:я\s+)?(?:еще\s+)?не смотрел\w*|непросмотренн\w*|(?:без|исключи\w*) (?:уже )?просмотренн\w*'):
        if free(m):
            hard.exclude_watched = True
            touched.add('exclude_watched')
            take(m.start(), m.end())

    # Negation is carried only across a coordinated list, never across a clause.
    last_end, negative = -1, False
    genre_matches = sorted((m.start(), m, genre) for genre, pattern in GENRE_PATTERNS.items() for m in matches(pattern))
    for _, m, genre in genre_matches:
        if not free(m):
            continue
        prefix = text[:m.start()]
        neg = re.search(r'(?<!\w)(?:без|кроме|не(?:\s+(?:хочу|люблю))?|исключи\w*)\s+(?:жанр\w*\s+)?$', prefix)
        # A list can contain unsupported traits: "без мистики и ужасов".
        inherited = _coordinated_negation(prefix)
        bridge = text[last_end:m.start()] if last_end >= 0 else ''
        negative = bool(neg or inherited) or (negative and bool(re.fullmatch(r'\s*(?:,|и|или|,\s*и)\s*', bridge)))
        field = 'excluded_genres' if negative else 'genres'
        if genre not in getattr(hard, field):
            getattr(hard, field).append(genre)
        touched.add(field)
        take(neg.start() if neg else m.start(), m.end())
        last_end = m.end()

    for key, (label, pattern, _) in THEMES.items():
        for m in matches(pattern):
            if free(m):
                # Unsupported theme negations are not inverted into preferences.
                prefix = text[:m.start()]
                if (re.search(r'(?<!\w)(?:без|не(?:\s+хочу)?|кроме)\s+$', prefix) or
                        _coordinated_negation(prefix)):
                    notes.append(f'Исключение темы «{label}» пока не поддерживается; оно не применено.')
                    continue
                soft.themes.append(key)
                touched.add('themes')
                take(m.start(), m.end())
    soft.themes = list(dict.fromkeys(soft.themes))
    if 'или' in text.split() and len(hard.genres) > 1:
        notes.append('Альтернативные жанры через «или» пока не поддерживаются. Сейчас обязательны все указанные жанры; удалите лишний.')

    # Mood tags may be searched literally; no continuous mood/pace metric exists.
    for m in matches(r'(?:без\s+)?мистик\w*|попроще|мрачн\w*|менее мрачн\w*|темп\w*|атмосфер\w*'):
        if free(m):
            notes.append(f'«{m.group()}»: в каталоге нет достоверной оценки этого признака; условие не применено.')
            take(m.start(), m.end())

    if re.search(r'(?<!\w)вдвоем(?!\w)', text):
        notes.append('Поиск использует профиль выбранного зрителя. Общий вкус двоих учитывается в «Выбрать вместе».')

    remainder = ''.join(' ' if used else char for char, used in zip(text, consumed))
    # Only remove harmless glue. In particular, keep leftover negation words.
    remainder = re.sub(r'(?<!\w)(?:хочу|хотим|покажи|найди|подбери|фильм\w*|что(?:-то|-нибудь)?|на|вечер|вдвоем|про|с|и|или|но|только|пожалуйста|мне)(?!\w)', ' ', remainder)
    remainder = re.sub(r'[\s,.;:!?«»"]+', ' ', remainder).strip()
    if remainder:
        notes.append(f'Не разобрано: «{remainder}». Эта часть запроса не влияет на подбор.')
    return {'criteria_json': criteria.model_dump_json(), 'notes': tuple(dict.fromkeys(notes)),
            'unparsed': remainder, 'touched': tuple(touched)}


def refine(previous: SearchCriteria, interpretation: dict) -> SearchCriteria:
    result = previous.model_copy(deep=True)
    parsed = interpretation['criteria']
    for field in interpretation['touched']:
        if field in {'themes', 'similar_title'}:
            setattr(result.soft, field, getattr(parsed.soft, field))
            if field == 'similar_title':
                result.soft.source_id = None
        else:
            setattr(result.hard, field, getattr(parsed.hard, field))
    return result
