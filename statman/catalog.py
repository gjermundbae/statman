"""Det semantiske laget — bevisst tynt.

Formålet er å tvinge fram at definisjon, enhet, kilde og forbehold står
skrevet ned ett sted, og at forbeholdene følger med tallene ut i analysen.
Fylles ut for hånd. Ikke generer ``caveats``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from statman import io

if TYPE_CHECKING:  # pragma: no cover - kun for typehinting
    import polars as pl

REQUIRED_FIELDS: tuple[str, ...] = ("label", "model", "column", "unit", "source")


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    label: str
    model: str
    column: str
    unit: str
    source: str
    caveats: tuple[str, ...] = ()
    breaks: tuple[str, ...] = ()

    def frame(self) -> pl.DataFrame:
        """Hele modelltabellen metrikken bor i."""
        return io.load(self.model)

    def series(self, *keep: str) -> pl.DataFrame:
        """Bare metrikkolonnen, pluss eventuelle nøkkelkolonner du vil ha med."""
        return self.frame().select([*keep, self.column])

    def note(self) -> str:
        """Ferdig forbeholdstekst til metodeavsnittet i en sakspakke."""
        lines = [f"{self.label} ({self.unit}). Kilde: {self.source}."]
        for caveat in self.caveats:
            lines.append(f"- {caveat}")
        for brk in self.breaks:
            lines.append(f"- Seriebrudd: {brk}")
        return "\n".join(lines)


def _parse(key: str, raw: dict[str, Any]) -> Metric:
    missing = [f for f in REQUIRED_FIELDS if not raw.get(f)]
    if missing:
        raise ValueError(f"Metrikken {key!r} mangler påkrevde felt: {', '.join(missing)}")
    return Metric(
        key=key,
        label=str(raw["label"]),
        model=str(raw["model"]),
        column=str(raw["column"]),
        unit=str(raw["unit"]),
        source=str(raw["source"]),
        caveats=tuple(raw.get("caveats") or ()),
        breaks=tuple(raw.get("breaks") or ()),
    )


def load_catalog(path: Path | None = None) -> dict[str, Metric]:
    """Les metrikkatalogen fra disk. Ingen caching — tester og notebooks vil ha ferskt."""
    import yaml

    target = path or io.catalog_path()
    if not target.exists():
        return {}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{target} må være et mapping av metrikknøkler")
    return {key: _parse(key, value or {}) for key, value in data.items()}


def metrics(path: Path | None = None) -> dict[str, Metric]:
    return load_catalog(path)


def metric(key: str, path: Path | None = None) -> Metric:
    catalog = load_catalog(path)
    if key not in catalog:
        known = ", ".join(sorted(catalog)) or "(katalogen er tom)"
        raise KeyError(f"Ukjent metrikk {key!r}. Kjente: {known}")
    return catalog[key]
