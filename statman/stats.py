"""Pearson-korrelasjon og tosidig p-verdi. Ingen scipy i prosjektet.

Skrevet for hånd én gang i ``examples/preben_borgerlig.py``, og flyttet hit
andre gang et eksempel trengte akkurat de samme to funksjonene — samme
regel som deflatering i ARCHITECTURE.md: én gang for hånd er greit, andre
gang er det en delt funksjon.
"""

from __future__ import annotations

import math


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy)


def _betacf(a: float, b: float, x: float, iterations: int = 200, eps: float = 3e-9) -> float:
    """Kjedebrøken i den regulariserte ufullstendige betafunksjonen (Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1e-30 if abs(d) < 1e-30 else d
    d = 1.0 / d
    h = d
    for m in range(1, iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1e-30 if abs(1.0 + aa * d) < 1e-30 else 1.0 + aa * d
        c = 1e-30 if abs(1.0 + aa / c) < 1e-30 else 1.0 + aa / c
        d, c = 1.0 / d, c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1e-30 if abs(1.0 + aa * d) < 1e-30 else 1.0 + aa * d
        c = 1e-30 if abs(1.0 + aa / c) < 1e-30 else 1.0 + aa / c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularisert ufullstendig betafunksjon I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_test_p(r: float, n: int) -> float:
    """Tosidig p-verdi for Pearsons r med n observasjoner, nullhypotese r=0."""
    if n <= 2:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t2 = r * r * df / (1 - r * r)
    return _betainc(df / 2, 0.5, df / (df + t2))
