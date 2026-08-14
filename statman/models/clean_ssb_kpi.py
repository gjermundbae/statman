"""clean-laget for SSB tabell 14700 — konsumprisindeksen.

Mekanisk lag: én rad per måned, med totalindeksen. Vi henter bare
``VareTjenesteGrp = '00'` («I alt»), fordi det er totalindeksen som brukes
til å deflatere lønn. Undergruppene finnes i kilden, og en analyse som
trenger dem kan hente dem uten å røre denne modellen.

Basisåret er kildens eget. SSB rebaserte til 2025=100 i 2026, og det er
derfor ingen konstant her sier hva basisen er — den leses av dataene, og en
rebasering hos SSB skal ikke kreve en kodeendring. Referanseperioden for
deflatering velges i mart-laget, der valget hører hjemme.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_KPI: Final[str] = "ssb/14700_kpi"

# «I alt» — totalindeksen. Koden står navngitt fordi '00' ikke er gjettbar.
TOTALINDEKS: Final[str] = "00"


@model(
    name="clean.konsumprisindeks",
    deps=[f"raw:{RAW_KPI}"],
    checks=[
        "unique:maaned",
        "not_null:indeks",
        "indeks > 0",
        "regexp_matches(maaned, '^[0-9]{4}M[0-9]{2}$')",
    ],
    doc="SSB 14700, totalindeksen (KPI) per måned. Basis er kildens egen.",
)
def clean_konsumprisindeks(ctx: Context) -> Any:
    ctx.register("_kpi", jsonstat.to_frame(ctx.raw_latest(RAW_KPI)))
    return ctx.sql(f"""
        select
            tid                      as maaned,
            cast(value as double)    as indeks
        from _kpi
        where value is not null
          and varetjenestegrp = '{TOTALINDEKS}'
          and lower(contentscode) = 'kpiindmnd'
        order by maaned
    """)
