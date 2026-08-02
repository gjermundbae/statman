"""clean-laget for SSB tabell 06913 — folkemengde og befolkningsendringer.

Mekanisk lag: json-stat2 brettes ut, kodene typenes, kolonnene får norske
navn. Ingen valg tas her. Tre ting er likevel verdt å vite:

* Regionkodene kommer prefikset (``K_3101``, ``F_31``) fordi vi ber om
  aggregerte kodelister. Prefikset strippes her, ikke i mart.
* Begge kodelistene er «sammenslåtte tidsserier»: historikken til kommuner
  som er slått sammen, er summert opp til 2024-inndelingen. Fylkeslista må
  være ``agg_KommFylkerHist`` og ikke ``agg_Fylker2024`` — den siste har
  bare tall fra fylkene slik de faktisk het det året, og summerer seg til
  1,5 millioner i 2011 i stedet for 4,9.
* Kommunelista har fire samlekategorier i tillegg til de 357 kommunene.
  Tre er tomme, men **«Delte kommuner og uoppgitt» (K_Rest) er det ikke**:
  den holder rundt 53 000 personer til og med 2019. Det er historikken til
  kommuner som ble delt i 2020, og som derfor ikke kan tilordnes én kommune
  i dagens inndeling. Summen av de 357 kommunene er altså *ikke* Norges
  folketall før 2020. Fylkestabellen har dem med, og differansen regnes ut
  og rapporteres i sakspakken.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_KOMMUNE: Final[str] = "ssb/06913_kommune"
RAW_FYLKE: Final[str] = "ssb/06913_fylke"

# SSBs ContentsCode -> vårt variabelnavn. Små bokstaver er hele
# transformasjonen, men lista står her for at et nytt eller omdøpt
# statistikkvariabelnavn hos SSB skal gi færre rader og ikke en stille
# ny kategori.
VARIABLER: Final[tuple[str, ...]] = (
    "Folkemengde",  # bestand per 1. januar i året
    "Fodselsoverskudd",  # strøm gjennom året
    "Nettoinnflytting",
    "Folketilvekst",
)

_VARIABEL_FILTER = ", ".join(f"'{code}'" for code in VARIABLER)


@model(
    name="clean.befolkning_kommune",
    deps=[f"raw:{RAW_KOMMUNE}"],
    checks=[
        "unique:kommunenummer,aar,variabel",
        "not_null:verdi",
        "length(kommunenummer) = 4",
    ],
    doc="SSB 06913 per kommune i 2024-inndeling. Lang form: kommune × år × variabel.",
)
def clean_befolkning_kommune(ctx: Context) -> Any:
    ctx.register("_kommune", jsonstat.to_frame(ctx.raw_latest(RAW_KOMMUNE)))
    return ctx.sql(f"""
        select
            replace(region, 'K_', '')   as kommunenummer,
            region_label                as kommune,
            cast(tid as integer)        as aar,
            lower(contentscode)         as variabel,
            cast(value as bigint)       as verdi
        from _kommune
        where value is not null
          and contentscode in ({_VARIABEL_FILTER})
          and regexp_matches(region, '^K_[0-9]{{4}}$')
        order by kommunenummer, aar, variabel
    """)


@model(
    name="clean.befolkning_fylke",
    deps=[f"raw:{RAW_FYLKE}"],
    checks=[
        "unique:fylkesnummer,aar,variabel",
        "not_null:fylke",
        "length(fylkesnummer) = 2",
    ],
    doc="SSB 06913 per fylke i 2024-inndeling, sammenslåtte tidsserier.",
)
def clean_befolkning_fylke(ctx: Context) -> Any:
    ctx.register("_fylke", jsonstat.to_frame(ctx.raw_latest(RAW_FYLKE)))
    return ctx.sql(f"""
        select
            replace(region, 'F_', '')   as fylkesnummer,
            region_label                as fylke,
            cast(tid as integer)        as aar,
            lower(contentscode)         as variabel,
            cast(value as bigint)       as verdi
        from _fylke
        where value is not null
          and contentscode in ({_VARIABEL_FILTER})
          and regexp_matches(region, '^F_[0-9]{{2}}$')
        order by fylkesnummer, aar, variabel
    """)
