"""clean-laget for utflytterroasteret.

Mekanisk lag, samme regel som ellers: typing, ingen vurderinger. Selve
vurderingen — hvem som kom med, og hvorfor — er tatt i
``statman/sources/utflyttere.py``, med kilde per rad.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

RAW_ROSTER: Final[str] = "utflyttere/roster"


@model(
    name="clean.utflyttere",
    deps=[f"raw:{RAW_ROSTER}"],
    checks=[
        "unique:navn",
        "unique:fifa_kode",
        "not_null:navn",
        "not_null:fifa_kode",
        "not_null:kilde_url",
    ],
    doc="Norske skatteutflyttere i utvalget: navn, land, by, år og kilde. Ett land per person.",
)
def clean_utflyttere(ctx: Context) -> Any:
    path = ctx.raw_latest(RAW_ROSTER)
    return ctx.sql(f"""
        select
            navn,
            fifa_kode,
            land_navn,
            sted,
            flyttet_aar::integer as flyttet_aar,
            notat,
            kilde_navn,
            kilde_url
        from read_json_auto('{path.as_posix()}')
        order by navn
    """)
