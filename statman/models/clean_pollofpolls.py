"""clean-laget for pollofpolls.no — snitt for stortingsvalg.

Mekanisk lag, men mindre mekanisk enn vanlig: kilden er en CSV, ikke
json-stat2, så det finnes ingen delt ``jsonstat.to_frame`` å hente
utbrettingen fra. Parsingen står derfor her i stedet for i ``sources/``,
som aldri skal tolke innhold — bare hente og skrive ned uendret.

To ting CSV-en krever, som ikke er et valg, bare et format å avkode riktig:

* Fila er Latin-1, uansett hva ``Content-Type``-headeren i HTTP-svaret sier.
  Avkodes feil blir ``Høyre`` til ``H�yre``.
* Hver celle er «oppslutning (mandater)» i én streng, som
  ``"22,6 (42)"`` — norsk desimalkomma og mandattall i parentes. Begge deler
  brettes ut til egne kolonner her.
"""

from __future__ import annotations

import csv
import io as _io
import re
from pathlib import Path
from typing import Any, Final

from statman.registry import Context, model

RAW_SNITT: Final[str] = "pollofpolls/stortinget_snitt"

_MAANEDER: Final[dict[str, int]] = {
    "Januar": 1, "Februar": 2, "Mars": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11,
    "Desember": 12,
}
_CELLE: Final[re.Pattern[str]] = re.compile(r"^(-?[\d,]+)\s*\((\d+)\)$")


def _parse(path: Path) -> Any:
    """CSV -> lang polars-DataFrame: år × måned × parti."""
    import polars as pl

    text = path.read_bytes().decode("latin-1")
    rows = list(csv.reader(_io.StringIO(text), delimiter=";"))
    partier = rows[0][1:]

    aar: list[int] = []
    maaned: list[int] = []
    parti: list[str] = []
    andel: list[float] = []
    mandater: list[int] = []
    for row in rows[1:]:
        navn, _, aartekst = row[0].partition("'")
        navn = navn.strip()
        if navn not in _MAANEDER:
            raise ValueError(f"Ukjent månedsnavn {navn!r} i {path} (rad {row!r})")
        for kolonne, celle in zip(partier, row[1:]):
            treff = _CELLE.match(celle.strip())
            if not treff:
                raise ValueError(f"Uventet celleformat {celle!r} i {path}")
            aar.append(2000 + int(aartekst))
            maaned.append(_MAANEDER[navn])
            parti.append(kolonne)
            andel.append(float(treff.group(1).replace(",", ".")))
            mandater.append(int(treff.group(2)))

    return pl.DataFrame(
        {
            "aar": aar,
            "maaned": maaned,
            "parti": parti,
            "andel_velgere_pst": andel,
            "mandater": mandater,
        }
    )


@model(
    name="clean.meningsmaling_parti",
    deps=[f"raw:{RAW_SNITT}"],
    checks=[
        "unique:aar,maaned,parti",
        "not_null:parti",
        "maaned >= 1 and maaned <= 12",
        "andel_velgere_pst >= 0",
        "mandater >= 0",
    ],
    doc="pollofpolls.no, snitt for stortingsvalg. Lang form: år × måned × parti.",
)
def clean_meningsmaling_parti(ctx: Context) -> Any:
    ctx.register("_meningsmaling", _parse(ctx.raw_latest(RAW_SNITT)))
    return ctx.sql("select * from _meningsmaling order by aar, maaned, parti")
