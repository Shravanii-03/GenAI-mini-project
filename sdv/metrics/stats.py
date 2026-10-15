"""Small statistics helpers: every reported number should come with an interval."""
import math
import random


def wilson_interval(successes: int, n: int, z: float = 1.96):
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(values, stat=None, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0):
    """Percentile bootstrap CI for a statistic (default: median)."""
    values = list(values)
    if not values:
        return (float("nan"), float("nan"))
    stat = stat or (lambda xs: sorted(xs)[len(xs) // 2])
    rng = random.Random(seed)
    stats = sorted(stat([rng.choice(values) for _ in values]) for _ in range(n_boot))
    return (stats[int(alpha / 2 * n_boot)], stats[min(n_boot - 1, int((1 - alpha / 2) * n_boot))])


def median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else float("nan")
