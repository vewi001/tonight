"""Sampling adapter over Tonight IQ scores; eligibility stays in personal.py."""
import math
import random


def weighted_pick(items, mode, rng=None):
    """Softmax keeps every candidate possible. Surprise flattens IQ weights."""
    temperature = 0.65 if mode == 'surprise' else 0.12
    peak = max(m['recommendation_score'] for m in items)
    weights = [math.exp((m['recommendation_score'] - peak) / temperature) for m in items]
    return (rng or random.SystemRandom()).choices(items, weights=weights, k=1)[0]
