"""mart-laget for utflyttertabellen: skatteutflyttere mot FIFA-rankingen.

Ett valg tas her, og det er selve poenget med saken: **differansen mellom
Norges FIFA-plassering og det nye landets plassering** avgjør om utflyttingen
telles som «rykket opp» eller «rykket ned» — ikke noe landet har gjort seg
fortjent til på banen etterpå, bare hvor det lå da rankingen sist ble satt
(20. juli 2026, se ``statman/sources/fifa.py``).

``differanse = norge_rangering - land_rangering``. Positiv betyr at det nye
landet er bedre plassert enn Norge (lavere rangeringstall), altså «rykket
opp». Negativ betyr at det er dårligere plassert, altså «rykket ned». Norges
egen rangering hentes med en kryssjoin mot én rad i ``clean.fifa_ranking``,
siden den samme referanseverdien skal brukes for alle radene.
"""

from __future__ import annotations

from typing import Any

from statman.registry import Context, model


@model(
    name="mart.utflyttere_fifa",
    deps=["clean.utflyttere", "clean.fifa_ranking"],
    checks=[
        "unique:navn",
        "not_null:differanse",
        "norge_rangering > 0",
        "land_rangering > 0",
    ],
    doc="Norske skatteutflyttere rangert etter om det nye landet ligger over eller under Norge på FIFA-rankingen.",
)
def utflyttere_fifa(ctx: Context) -> Any:
    return ctx.sql("""
        with norge as (
            select rangering as norge_rangering, poeng as norge_poeng
            from clean_fifa_ranking
            where fifa_kode = 'NOR'
        )
        select
            u.navn,
            u.fifa_kode,
            u.land_navn,
            u.sted,
            u.flyttet_aar,
            u.notat,
            u.kilde_navn,
            u.kilde_url,
            f.lag              as fifa_lagnavn,
            f.rangering         as land_rangering,
            f.poeng             as land_poeng,
            n.norge_rangering,
            n.norge_poeng,
            n.norge_rangering - f.rangering  as differanse,
            (n.norge_rangering - f.rangering) > 0  as rykket_opp
        from clean_utflyttere u
        join clean_fifa_ranking f on f.fifa_kode = u.fifa_kode
        cross join norge n
        order by differanse desc
    """)
