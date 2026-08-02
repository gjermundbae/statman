"""Syntetisk kilde — for å teste hele kjeden uten nettverk.

Lager to serier som ligner nok på virkeligheten til at eksempelet må løse et
ekte problem: nominelle kraftpriser må deflateres før de kan sammenlignes
over tid. Dataene er deterministiske gitt ``seed``.

Dette er *ikke* ekte tall. Modellene og grafen merker dem som syntetiske.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Final

SOURCE: Final[str] = "synthetic"
AREAS: Final[tuple[str, ...]] = ("NO1", "NO2", "NO3", "NO4", "NO5")
START_YEAR: Final[int] = 2015
END_YEAR: Final[int] = 2025

# Sørlige prisområder rammes hardere av prissjokket enn de nordlige.
_SHOCK_WEIGHT: Final[dict[str, float]] = {
    "NO1": 1.0, "NO2": 1.15, "NO3": 0.25, "NO4": 0.15, "NO5": 0.95,
}


def _months() -> list[tuple[int, int]]:
    return [(y, m) for y in range(START_YEAR, END_YEAR + 1) for m in range(1, 13)]


def _shock(year: int, month: int) -> float:
    """Prissjokk fra høsten 2021 til våren 2023, med opp- og nedtrapping."""
    t = year * 12 + month
    start, peak, end = 2021 * 12 + 9, 2022 * 12 + 12, 2023 * 12 + 4
    if t < start or t > end:
        return 0.0
    if t <= peak:
        return (t - start) / (peak - start)
    return (end - t) / (end - peak)


def generate_kraftpris(seed: int = 1) -> list[dict[str, object]]:
    """Månedlig kraftpris i øre/kWh per prisområde."""
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for year, month in _months():
        season = 1.0 + 0.30 * math.cos((month - 1) / 12 * 2 * math.pi)
        for area in AREAS:
            base = 32.0 * season * (1.0 + 0.02 * (year - START_YEAR))
            price = base + 190.0 * _SHOCK_WEIGHT[area] * _shock(year, month)
            price *= rng.uniform(0.90, 1.10)
            rows.append(
                {
                    "periode": f"{year}M{month:02d}",
                    "prisomrade": area,
                    "ore_per_kwh": round(price, 2),
                }
            )
    return rows


def generate_kpi(seed: int = 2) -> list[dict[str, object]]:
    """Månedlig konsumprisindeks, 2015 = 100."""
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    index = 100.0
    for year, month in _months():
        annual = 0.055 if year in (2022, 2023) else 0.022
        index *= (1 + annual) ** (1 / 12) * rng.uniform(0.999, 1.001)
        rows.append({"periode": f"{year}M{month:02d}", "indeks_2015": round(index, 3)})
    return rows


def ingest(seed: int = 1) -> dict[str, Path]:
    """Skriv begge seriene til rålaget, som om de kom fra et API."""
    from statman import io

    written: dict[str, Path] = {}
    for dataset, rows, note in (
        ("kraftpris", generate_kraftpris(seed), "Syntetisk kraftpris, øre/kWh"),
        ("kpi", generate_kpi(seed + 1), "Syntetisk konsumprisindeks, 2015=100"),
    ):
        payload = json.dumps(rows, ensure_ascii=False, indent=None).encode("utf-8")
        written[dataset] = io.write_raw(
            SOURCE,
            dataset,
            payload,
            {
                "endpoint": "synthetic://generator",
                "params": {"seed": seed},
                "license": "syntetiske data — ikke ekte statistikk",
                "note": note,
                "rows": len(rows),
            },
        )
    return written
