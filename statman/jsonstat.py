"""json-stat2 → lang tabell.

SSBs PxWebApi 2.0 svarer med json-stat2: én flat liste med verdier, pluss en
beskrivelse av dimensjonene lista skal brettes ut fra. Denne modulen gjør bare
den brettingen, og vet ingenting om hvilken tabell den ser på.

Den ligger her og ikke i ``sources/`` fordi rålaget aldri skal tolke innhold.
Det er clean-modellene som kaller hit.

Utformen er lang: én rad per celle, én kolonne per dimensjon med koden, én
``<dim>_label``-kolonne med teksten, pluss ``value`` og ``status``.
Kolonnenavnene er dimensjons-ID-ene i små bokstaver, så ``ContentsCode``
blir ``contentscode``.
"""

from __future__ import annotations

import json
from math import prod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - kun for typehinting
    import polars as pl

HEADER_FIELDS: tuple[str, ...] = ("label", "source", "updated")


def load(source: dict[str, Any] | Path | str) -> dict[str, Any]:
    """Et json-stat2-dokument, enten det kommer som dict eller filsti."""
    if isinstance(source, dict):
        return source
    return json.loads(Path(source).read_text(encoding="utf-8"))


def header(source: dict[str, Any] | Path | str) -> dict[str, str]:
    """Tabellnavn, kilde og SSBs oppdateringstidspunkt — til metodeavsnittet."""
    doc = load(source)
    return {field: str(doc.get(field, "")) for field in HEADER_FIELDS}


def column_name(dimension_id: str) -> str:
    return dimension_id.lower()


def to_frame(source: dict[str, Any] | Path | str) -> pl.DataFrame:
    """Brett ut et json-stat2-dokument til én rad per celle."""
    import polars as pl

    doc = load(source)
    ids = [str(i) for i in doc["id"]]
    sizes = [int(s) for s in doc["size"]]
    if len(ids) != len(sizes):
        raise ValueError(f"json-stat2: {len(ids)} dimensjoner men {len(sizes)} størrelser")

    cells = prod(sizes) if sizes else 0
    columns: dict[str, pl.Series] = {}

    for axis, dimension_id in enumerate(ids):
        codes, labels = _category(doc["dimension"][dimension_id], sizes[axis])
        # Radrekkefølgen er row-major: siste dimensjon varierer raskest.
        inner = prod(sizes[axis + 1 :])
        outer = prod(sizes[:axis])
        positions = [i for _ in range(outer) for i in range(sizes[axis]) for _ in range(inner)]
        name = column_name(dimension_id)
        columns[name] = pl.Series(name, [codes[i] for i in positions], dtype=pl.Utf8)
        columns[f"{name}_label"] = pl.Series(
            f"{name}_label", [labels[i] for i in positions], dtype=pl.Utf8
        )

    columns["value"] = pl.Series("value", _values(doc.get("value"), cells), dtype=pl.Float64)
    columns["status"] = pl.Series("status", _status(doc.get("status"), cells), dtype=pl.Utf8)
    return pl.DataFrame(columns)


def _category(dimension: dict[str, Any], size: int) -> tuple[list[str], list[str]]:
    """Kodene til en dimensjon i riktig rekkefølge, med tilhørende tekst."""
    category = dimension.get("category") or {}
    index = category.get("index")
    labels: dict[str, Any] = category.get("label") or {}

    if isinstance(index, dict):
        codes = [code for code, _ in sorted(index.items(), key=lambda kv: int(kv[1]))]
    elif isinstance(index, list):
        codes = [str(code) for code in index]
    else:  # én-verdis dimensjoner kan mangle index helt
        codes = [str(code) for code in labels]

    if len(codes) != size:
        raise ValueError(f"json-stat2: dimensjonen har {len(codes)} koder, men size sier {size}")
    return codes, [str(labels.get(code, code)) for code in codes]


def _values(raw: Any, cells: int) -> list[float | None]:
    """``value`` er enten en tett liste eller et glissent kart fra celleindeks."""
    if isinstance(raw, dict):
        out: list[float | None] = [None] * cells
        for key, value in raw.items():
            out[int(key)] = value
        return out
    values = list(raw or [])
    if len(values) != cells:
        raise ValueError(f"json-stat2: {len(values)} verdier, men dimensjonene gir {cells} celler")
    return values


def _status(raw: Any, cells: int) -> list[str | None]:
    """``status`` markerer hvorfor en celle er tom — SSB bruker '..' og ':'."""
    if raw is None:
        return [None] * cells
    if isinstance(raw, str):
        return [raw] * cells
    if isinstance(raw, dict):
        out: list[str | None] = [None] * cells
        for key, value in raw.items():
            try:
                out[int(key)] = str(value)
            except (TypeError, ValueError):
                continue  # nøkler som ikke er celleindekser angår ikke oss
        return out
    return [None if value is None else str(value) for value in raw]
