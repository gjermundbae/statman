"""clean-laget for SSB tabell 10467 — fødte etter fornavn.

Rådata er allerede filtrert til étt fornavn i selve SSB-kallet (se
``examples/preben_borgerlig.py``), ikke her — rålaget skriver ned det
API-et faktisk svarte, og clean-laget tolker det uendret. Mekanisk lag,
lang form: begge statistikkvariablene (antall og andel) står som egne
rader, ikke egne kolonner. Pivoteringen til bredt format, der et valg om
hvordan mangler skal håndteres tas, hører til i mart.

Verdien mangler for enkelte år av to ulike grunner, som begge skal bevares
som ``null`` og ikke fylles inn:

* ``antall`` (SSBs ``Personer``) er ikke oppgitt før 1945.
* Nyere år kan være undertrykt (færre enn fire personer) eller ennå ikke
  ferdig talt opp — 2025 er begge deler for Preben i skrivende stund, siden
  navngivningsår (fra 2021) etterslepes.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_NAVN: Final[str] = "ssb/10467_preben"


@model(
    name="clean.navn_preben",
    deps=[f"raw:{RAW_NAVN}"],
    checks=[
        "unique:aar,variabel",
        "not_null:aar",
        "not_null:variabel",
    ],
    doc="SSB 10467, filtrert til Preben. Lang form: år × variabel (fødte, andel).",
)
def clean_navn_preben(ctx: Context) -> Any:
    ctx.register("_navn", jsonstat.to_frame(ctx.raw_latest(RAW_NAVN)))
    return ctx.sql("""
        select
            cast(tid as integer)   as aar,
            fornavn_label          as fornavn,
            lower(contentscode)    as variabel,
            value                  as verdi,
            status
        from _navn
        order by aar, variabel
    """)
