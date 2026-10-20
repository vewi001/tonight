"""Conservative mood evidence from catalog metadata, never inferred film facts.

Genre is a discovery hint, not proof of emotional tone. Explicitly heavy
subjects veto light/cozy discovery. Missing subjects do not prove their absence.
The vocabulary is deliberately inspectable; this is not a content advisory.
"""
import re

LIGHT_TAGS = {'feel-good', 'feelgood', 'light-hearted', 'lighthearted',
              'heartwarming', 'cozy', 'уютный', 'добрый юмор'}
HEAVY = re.compile(
    r'\b(?:концлагер\w*|холокост\w*|геноцид\w*|нацист\w*|самоубий\w*|'
    r'суицид\w*|изнасил\w*|пытк\w*|смертельн\w*|неизлечим\w*|'
    r'онкологи\w*|серийн\w* убий\w*|убийств\w*|воин\w*|войн\w*|'
    r'holocaust|concentration camp|genocide|suicide|rape|torture|'
    r'terminal illness|cancer|serial killer|murder|war)\b', re.I)


def mood_evidence(movie, mood, genres):
    """Return eligibility, strength, and a truthful explanation.

    Positive tags are used as *attributed* evidence only; explicit contrary
    evidence takes precedence even over a feel-good tag.
    """
    actual = set(movie.get('genres') or [])
    matched = sorted(actual & genres)
    if not genres:
        return True, 0., ''
    if not matched:
        return False, 0., ''
    if mood in {'cozy', 'laugh'}:
        text = ' '.join([movie.get('overview') or '', *(movie.get('keywords') or [])])
        if actual & {'хоррор', 'триллер', 'военный', 'криминал'} or HEAVY.search(text):
            return False, 0., ''
        tags = sorted({str(k).strip().casefold() for k in movie.get('keywords') or []} & LIGHT_TAGS)
        if tags:
            return True, .18, f'В каталоге есть тематическая отметка «{tags[0]}». Это подсказка, а не гарантия настроения.'
    return True, .06, f'Приблизительно по жанрам: {", ".join(matched[:2])}. Эмоциональный тон не подтверждён.'
