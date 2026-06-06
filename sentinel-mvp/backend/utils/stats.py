"""Tiny pure-Python linear regression (no numpy needed).

Used to turn an RSS-vs-time window into a slope (bytes/sec) and R². Slope is the
leak signal; R² gates on it being a *sustained* trend, not noise (CLAUDE.md #2).
"""

from typing import List, Tuple


def linregress(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Return (slope, r_squared). slope is in y-units per x-unit."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    syy = sum((y - mean_y) ** 2 for y in ys)

    if sxx == 0:
        return 0.0, 0.0

    slope = sxy / sxx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    return slope, r2
