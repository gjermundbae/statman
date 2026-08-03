"""clean-laget for SSB tabell 09624 — velgere etter parti.

Selvrapportert stemmegivning fra SSBs valgundersøkelse (begge kjønn), ikke
opptalte valgresultater — se docstringen i
``examples/preben_borgerlig.py`` for hvorfor det er dette og ikke løpende
meningsmålinger som brukes. Mekanisk lag: alle ti partiene/listene SSB
rapporterer blir med, uansett hvor små de er. Hvilke som regnes som
«borgerlige» er et valg, og tas i mart, ikke her.

Et parti mangler verdi de årene det ikke fantes eller ikke ble skilt ut som
egen kategori ennå — Fremskrittspartiet i 1969 er eksempelet som betyr noe
for denne analysen. Det står som ``null``, ikke null prosent.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_VELGERE: Final[str] = "ssb/09624_velgere"


@model(
    name="clean.velgere_parti",
    deps=[f"raw:{RAW_VELGERE}"],
    checks=[
        "unique:aar,parti",
        "not_null:aar",
        "not_null:parti",
        "andel_velgere_pst is null or (andel_velgere_pst >= 0 and andel_velgere_pst <= 100)",
    ],
    doc="SSB 09624, begge kjønn. Lang form: valgår × parti, selvrapportert stemmegivning.",
)
def clean_velgere_parti(ctx: Context) -> Any:
    ctx.register("_velgere", jsonstat.to_frame(ctx.raw_latest(RAW_VELGERE)))
    return ctx.sql("""
        select
            cast(tid as integer)   as aar,
            politparti              as parti,
            politparti_label        as parti_navn,
            value                   as andel_velgere_pst,
            status
        from _velgere
        order by aar, parti
    """)
