"""Lønn for flygeledere (STYRK-08 3154) — ett yrke, to kilder, ett hull.

Yrket er for lite til å ha egne SSB-tabeller; alt her kommer fra de samme
uttrekkene ``mart_arbeidsmarked.py`` allerede bruker for alle 407 yrker,
filtrert til ett. Grunnen til at flygeledere får sin egen mart-modell
likevel, og ikke bare et filter i analysen, er at yrket oppfører seg
annerledes enn de fleste andre 407 på to punkter som ellers ville gjort
tallene feil uten at noe feilet synlig:

**Kvartalstabellen (11658) har medianlønn for flygeledere først fra
2025K4.** Alle 39 kvartalene før det er ``null`` i kilden — ikke i vår
uthenting, se raw-svaret selv. Den årlige reserven (11418) dekker
2015–2020 og 2025, men **ikke 2021–2024**: heller ikke der finnes tallet,
i noen av kildene. Det hullet fylles ikke her. Se ``mart.flygeledere_lonn``.

**Den generelle tidsserien i ``mart.arbeidsmarked_yrke_aar`` mister hele
2025 for akkurat dette yrket**, uten at noen sjekk der fanger det: den
modellen ankrer alle årspunkter til samme kvartalsnummer som det siste
kvartalet i serien (K2), og *bestanden* for flygeledere mangler nettopp
2025K2 (og 2025K3 — se ``clean.yrke_kvartal``, som har 581 av 583 yrker i
begge). Bestand-CTE-en der er en inner join mot det ankerkvartalet, så
2025-raden for yrke 3154 forsvinner sporløst i stedet for å stå med
tomme celler. Det er ikke en feil i den modellen — den fikk aldri en
bestandsverdi å joine mot — men det er grunnen til at denne saken bygger
egne tabeller på full kvartalsserie i stedet for å lese av den
eksisterende.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

YRKE: Final[str] = "3154"

# Referansen alle reallønnstall her deflateres til: novemberindeksen det
# siste året den årlige lønnsreserven dekker. Valgt fordi den årlige kilden
# (11418) selv måler i november, så referansen er samme måned som halve
# serien allerede er i — ikke et vilkårlig "nyeste kvartal" som ville gjort
# de to kildene enda vanskeligere å lese sammen.
KPI_REFERANSE_MAANED: Final[str] = "2025M11"


@model(
    name="mart.flygeledere_lonn",
    deps=[
        "clean.yrke_lonn_aar",
        "clean.yrke_lonn_kvartal",
        "clean.konsumprisindeks",
        "mart.konsumpris_kvartal",
        "clean.styrk",
    ],
    checks=[
        "unique:kilde,periode",
        "min_rows:1",
        "not_null:yrke_navn",
        "median_lonn_nominell > 0",
        "kpi_referanse > 0",
        "median_lonn_realt > 0",
        "kilde in ('aarlig', 'kvartalsvis')",
        "length(yrke) = 4",
    ],
    doc="Median månedslønn for flygeledere, årlig (11418) og kvartalsvis (11658), i ett langt format.",
)
def mart_flygeledere_lonn(ctx: Context) -> Any:
    """To kilder i lang form — én rad per (kilde, periode), aldri sydd sammen.

    Radene fra de to kildene deflateres til **samme** referanse (november
    det siste året 11418 dekker), så et yrke som bytter kilde ikke også
    bytter prisbasis midt i en sammenligning. Men de blandes aldri til én
    serie: en figur som tegner dem må bruke to atskilte streker, ikke én
    som hopper over 2021–2024 som om den var målt der. Se moduldocstringen.
    """
    return ctx.sql(f"""
        with aarlig as (
            select
                '{YRKE}'                                     as yrke,
                'aarlig'                                      as kilde,
                cast(l.aar as varchar)                        as periode,
                l.aar                                         as aar,
                cast(l.aar as double) + 10.0 / 12.0            as periode_x,
                l.median_lonn_arlig                            as median_lonn_nominell,
                k.indeks                                       as kpi_referanse
            from clean_yrke_lonn_aar l
            left join clean_konsumprisindeks k
                on k.maaned = cast(l.aar as varchar) || 'M11'
            where l.yrke = '{YRKE}'
        ),
        kvartalsvis as (
            select
                '{YRKE}'                                     as yrke,
                'kvartalsvis'                                  as kilde,
                l.kvartal                                      as periode,
                cast(substr(l.kvartal, 1, 4) as integer)       as aar,
                cast(substr(l.kvartal, 1, 4) as integer)
                    + (cast(substr(l.kvartal, 6, 1) as integer) - 1) / 4.0
                    + 1.0 / 8.0                                 as periode_x,
                l.median_lonn                                  as median_lonn_nominell,
                k.kpi                                          as kpi_referanse
            from clean_yrke_lonn_kvartal l
            join mart_konsumpris_kvartal k on k.kvartal = l.kvartal
            where l.yrke = '{YRKE}' and l.median_lonn > 0
        ),
        samlet as (
            select * from aarlig
            union all
            select * from kvartalsvis
        ),
        referanse as (
            select indeks as kpi_basis
            from clean_konsumprisindeks
            where maaned = '{KPI_REFERANSE_MAANED}'
        )
        select
            s.yrke                                             as yrke,
            y.navn                                              as yrke_navn,
            s.kilde                                             as kilde,
            s.periode                                           as periode,
            s.aar                                                as aar,
            s.periode_x                                         as periode_x,
            s.median_lonn_nominell                               as median_lonn_nominell,
            s.kpi_referanse                                      as kpi_referanse,
            s.median_lonn_nominell * r.kpi_basis / s.kpi_referanse as median_lonn_realt
        from samlet s
        cross join referanse r
        join clean_styrk y on y.kode = s.yrke and y.nivaa = 4
        order by s.kilde, s.periode
    """)


@model(
    name="mart.flygeledere_bestand_siste",
    deps=["clean.yrke_kvartal"],
    checks=["min_rows:1", "unique:yrke", "lonnstakere > 0"],
    doc="Antall flygeledere i det nyeste kvartalet der bestanden faktisk er publisert.",
)
def mart_flygeledere_bestand_siste(ctx: Context) -> Any:
    """Siste kvartal — ikke nødvendigvis *det* siste, se moduldocstringen.

    Bestanden for flygeledere mangler 2025K2 og 2025K3 i kilden (581 av 583
    yrker har dem, flygeledere er ikke blant de 581). ``qualify`` tar det
    nyeste kvartalet som *finnes*, i stedet for å anta at det er det samme
    som resten av 407-yrkessaken bruker.
    """
    return ctx.sql(f"""
        select
            yrke                                as yrke,
            yrke_navn                           as yrke_navn,
            kvartal                             as kvartal,
            cast(lonnstakere as bigint)         as lonnstakere
        from clean_yrke_kvartal
        where yrke = '{YRKE}'
        qualify row_number() over (order by kvartal desc) = 1
    """)
