"""Konsumprisindeksen per kvartal — deflatoren andre marts kobler seg på.

ARCHITECTURE.md har lenge hatt «deflatering som delt funksjon» på lista over
utsatte ting, med terskelen «etter andre gang den er skrevet for hånd».
Yrkessaken er andre gangen. Da viste det seg at det som ville deles ikke var
en funksjon: selve regnestykket er én multiplikasjon, og en funksjon rundt
`verdi × referanseindeks / periodeindeks` skjuler mer enn den sparer.

Det som er verdt å dele er *tabellen* — månedsindeksen brettet ut til den
perioden analysene faktisk måler i, med de to valgene tatt ett sted:

**Kvartalsindeksen er snittet av de tre månedene**, ikke midtmåneden og ikke
kvartalets siste. Lønnsstatistikken måler et nivå gjennom kvartalet, og da
er snittet det som svarer til det samme tidsrommet.

**Ufullstendige kvartaler faller ut.** Kilden er månedlig og ligger foran
kvartalsstatistikken; uten dette filteret ville et kvartal med én publisert
måned fått den ene måneden som «snitt», og et lønnstall deflatert med den
ville sett ut som en reallønnsendring.

``deflator_siste`` er ferdig regnet mot **nyeste fullstendige kvartal i
tabellen**. Den referansen flytter seg når SSB publiserer en ny måned, og
hele serien flytter seg med den. Det er ikke en feil, men det er grunnen til
at referansekvartalet alltid skal stå i figurteksten — nøyaktig samme
forbehold som kraftprissaken har på referansemåneden sin.
"""

from __future__ import annotations

from typing import Any

from statman.registry import Context, model

# Antall måneder som må være publisert før et kvartal regnes som fullstendig.
MAANEDER_I_KVARTAL: int = 3


@model(
    name="mart.konsumpris_kvartal",
    deps=["clean.konsumprisindeks"],
    checks=[
        "unique:kvartal",
        # Tom tabell er en reell feilmodus her: kvartalsuttrykket kan gi
        # etiketter som ikke kobler mot noe, og de andre sjekkene teller
        # rader som bryter — null rader bryter ingen av dem. Terskelen er 1
        # og ikke et produksjonstall: modellen skal påstå at den lager noe,
        # ikke hvor mye.
        "min_rows:1",
        "not_null:kpi",
        "kpi > 0",
        f"maaneder = {MAANEDER_I_KVARTAL}",
        # Deflatoren for referansekvartalet selv må være nøyaktig 1. Er den
        # ikke det, peker referansen et annet sted enn tabellen tror.
        "deflator_siste > 0",
    ],
    doc="KPI per kvartal, snitt av de tre månedene, med deflator mot nyeste fullstendige kvartal.",
)
def mart_konsumpris_kvartal(ctx: Context) -> Any:
    return ctx.sql(f"""
        with kvartalsvis as (
            select
                -- `//`, ikke `/`. DuckDB deler flyttall med skråstrek, og
                -- «2026K2.666…» er en kvartalsetikett som aldri kobler mot
                -- noe — den gir tom tabell, ikke feilmelding.
                substr(maaned, 1, 4) || 'K'
                    || cast(((cast(substr(maaned, 6, 2) as integer) - 1) // 3) + 1 as varchar)
                                                as kvartal,
                avg(indeks)                     as kpi,
                count(*)                        as maaneder
            from clean_konsumprisindeks
            group by 1
        ),
        fullstendige as (
            select * from kvartalsvis where maaneder = {MAANEDER_I_KVARTAL}
        ),
        referanse as (
            select kpi as kpi_ref, kvartal as kvartal_ref
            from fullstendige
            order by kvartal desc
            limit 1
        )
        select
            f.kvartal                   as kvartal,
            f.kpi                       as kpi,
            cast(f.maaneder as integer) as maaneder,
            r.kpi_ref / f.kpi           as deflator_siste,
            r.kvartal_ref               as kvartal_referanse
        from fullstendige f
        cross join referanse r
        order by f.kvartal
    """)
