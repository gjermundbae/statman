"""mart-laget: her tas valgene.

Det ene valget som betyr noe her er deflateringen. Nominelle kraftpriser fra
2015 og 2025 er ikke sammenlignbare, og en graf som viser dem side om side
uten å si fra er en av de vanligste feilene i denne sjangeren. Vi regner om
til faste kroner målt i siste måned i serien, og skriver det i katalogen.
"""

from __future__ import annotations

from typing import Any

from statman.registry import Context, model


@model(
    name="mart.kraftpris_maaned",
    deps=["clean.kraftpris", "clean.kpi"],
    checks=[
        "unique:month,prisomrade",
        "not_null:ore_nominell",
        "ore_nominell > 0",
        "ore_faste_kroner > 0",
    ],
    doc="Kraftpris per måned og prisområde, nominelt og i faste kroner, med 12-mnd endring.",
)
def kraftpris_maaned(ctx: Context) -> Any:
    return ctx.sql("""
        with referanse as (
            select indeks_2015 as kpi_ref
            from clean_kpi
            order by month desc
            limit 1
        ),
        koblet as (
            select
                k.month,
                k.prisomrade,
                k.ore_per_kwh                               as ore_nominell,
                p.indeks_2015                               as kpi,
                k.ore_per_kwh * r.kpi_ref / p.indeks_2015   as ore_faste_kroner
            from clean_kraftpris k
            join clean_kpi p on p.month = k.month
            cross join referanse r
        ),
        med_endring as (
            -- Vinduet ligger i eget steg så det regnes på uavrundede tall og
            -- ikke kan forveksles med aliasene i sluttselektet.
            select
                *,
                ore_faste_kroner
                    / lag(ore_faste_kroner, 12)
                        over (partition by prisomrade order by month)
                    - 1 as endring_12m_realt
            from koblet
        )
        select
            month,
            prisomrade,
            round(ore_nominell, 2)     as ore_nominell,
            round(ore_faste_kroner, 2) as ore_faste_kroner,
            round(kpi, 3)              as kpi,
            endring_12m_realt
        from med_endring
        order by month, prisomrade
    """)
