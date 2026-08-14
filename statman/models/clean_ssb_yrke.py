"""clean-laget for SSBs yrkesfordelte tabeller — 11658 og 14789.

Mekanisk lag: json-stat2 brettes ut, kodene typenes, kolonnene får norske
navn. Tre ting er verdt å vite:

* **Alle kodenivåer beholdes.** ``Yrke``-dimensjonen inneholder både de 407
  fireside yrkene og aggregatene over dem — hovedgrupper, yrkesgrupper,
  yrkesundergrupper og totalen ``0-9``. Vi filtrerer ikke, fordi det å velge
  ett nivå er et valg, og fordi mart-laget trenger totalen: at de 407 yrkene
  summerer seg til nøyaktig ``0-9`` er sjekken som sier at flisediagrammet
  dekker hele arbeidsmarkedet og ikke bare mesteparten av det.
* **Statistikkvariabelnavnet beholdes slik SSB skriver det**, bare i små
  bokstaver. Det gir ``lonsstakere`` — SSBs egen skrivemåte, med én n. Å
  rette den her ville skjult den dagen SSB retter den selv; slik gir en
  omdøpt variabel færre rader og en feilet sjekk i stedet for en stille ny
  kategori.
* **Tomme celler faller ut.** SSB publiserer ikke medianlønn for yrker med
  for få observasjoner. De radene finnes ikke her, og blir dermed null i
  mart-koblingen framfor å bli forvekslet med en målt null.

Yrkeskoden er den samme STYRK-08-koden i begge tabellene, så de kobler rett
på hverandre og på ``clean.styrk``.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_KVARTAL: Final[str] = "ssb/11658_kvartal"
RAW_LONN_KVARTAL: Final[str] = "ssb/11658_lonn_kvartal"
RAW_SISTE: Final[str] = "ssb/11658_siste"
RAW_KJONN: Final[str] = "ssb/11658_kjonn"
RAW_ALDER: Final[str] = "ssb/11658_alder"
RAW_SYKEFRAVAER: Final[str] = "ssb/14789_sykefravaer"

# Statistikkvariablene vi henter fra 11658. Lista står her, ikke bare i
# ingest-funksjonen, fordi den er kontrakten clean-laget kontrollerer mot.
VARIABLER: Final[tuple[str, ...]] = (
    "Lonsstakere",  # antall personer med jobben som hovedarbeidsforhold
    "MedianMndLonn",  # median månedslønn, kroner
    "GjsnAlder",  # gjennomsnittsalder, år
    "GjAvtArbtid",  # gjennomsnittlig avtalt arbeidstid, timer per uke
)
VARIABLER_KJONN: Final[tuple[str, ...]] = ("Lonsstakere", "MedianMndLonn")

_FILTER = ", ".join(f"'{code.lower()}'" for code in VARIABLER)
_FILTER_KJONN = ", ".join(f"'{code.lower()}'" for code in VARIABLER_KJONN)


@model(
    name="clean.yrke_kvartal",
    deps=[f"raw:{RAW_KVARTAL}"],
    checks=[
        "unique:yrke,kvartal",
        "not_null:yrke_navn",
        "lonnstakere >= 0",
        "regexp_matches(kvartal, '^[0-9]{4}K[1-4]$')",
    ],
    doc="SSB 11658, antall lønnstakere per yrke og kvartal. Hele serien.",
)
def clean_yrke_kvartal(ctx: Context) -> Any:
    ctx.register("_kvartal", jsonstat.to_frame(ctx.raw_latest(RAW_KVARTAL)))
    return ctx.sql("""
        select
            yrke                     as yrke,
            yrke_label               as yrke_navn,
            tid                      as kvartal,
            cast(value as bigint)    as lonnstakere
        from _kvartal
        where value is not null
          and lower(contentscode) = 'lonsstakere'
        order by yrke, kvartal
    """)


@model(
    name="clean.yrke_lonn_kvartal",
    deps=[f"raw:{RAW_LONN_KVARTAL}"],
    checks=[
        "unique:yrke,kvartal",
        "not_null:yrke_navn",
        "median_lonn >= 0",
        "regexp_matches(kvartal, '^[0-9]{4}K[1-4]$')",
    ],
    doc="SSB 11658, median månedslønn per yrke og kvartal. Hele serien.",
)
def clean_yrke_lonn_kvartal(ctx: Context) -> Any:
    """Medianlønna kvartal for kvartal.

    Nullene beholdes her, som ellers i denne fila: en median på null kroner
    er ikke en lønn, men det er kildens tall, og å tolke det er mart-lagets
    jobb. Se ``clean.yrke_kjonn`` for den samme avveiningen.
    """
    ctx.register("_lonn", jsonstat.to_frame(ctx.raw_latest(RAW_LONN_KVARTAL)))
    return ctx.sql("""
        select
            yrke                     as yrke,
            yrke_label               as yrke_navn,
            tid                      as kvartal,
            cast(value as double)    as median_lonn
        from _lonn
        where value is not null
          and lower(contentscode) = 'medianmndlonn'
        order by yrke, kvartal
    """)


@model(
    name="clean.yrke_siste",
    deps=[f"raw:{RAW_SISTE}"],
    checks=[
        "unique:yrke,variabel",
        "not_null:yrke_navn",
        f"variabel in ({_FILTER})",
        "regexp_matches(kvartal, '^[0-9]{4}K[1-4]$')",
    ],
    doc="SSB 11658, siste kvartal. Lang form: yrke × variabel.",
)
def clean_yrke_siste(ctx: Context) -> Any:
    ctx.register("_siste", jsonstat.to_frame(ctx.raw_latest(RAW_SISTE)))
    return ctx.sql(f"""
        select
            yrke                     as yrke,
            yrke_label               as yrke_navn,
            tid                      as kvartal,
            lower(contentscode)      as variabel,
            cast(value as double)    as verdi
        from _siste
        where value is not null
          and lower(contentscode) in ({_FILTER})
        order by yrke, variabel
    """)


@model(
    name="clean.yrke_kjonn",
    deps=[f"raw:{RAW_KJONN}"],
    checks=[
        "unique:yrke,kjonn,variabel",
        "kjonn in ('kvinner', 'menn')",
        f"variabel in ({_FILTER_KJONN})",
        # Ikke `> 0`. I 24 av de minste yrkene har det ene kjønnet null
        # lønnstakere, og da skriver SSB medianlønn 0 i åtte av dem. En
        # median på null kroner er ikke en målt lønn — den er det kilden
        # skriver når det ikke er noen å regne median for. Vi beholder
        # tallet slik det kom, og lar mart-laget avgjøre at det ikke er en
        # lønn. Det er nettopp den slags vurdering clean-laget ikke skal ta.
        "verdi >= 0",
    ],
    doc="SSB 11658 delt på kjønn, siste kvartal. Lang form: yrke × kjønn × variabel.",
)
def clean_yrke_kjonn(ctx: Context) -> Any:
    ctx.register("_kjonn", jsonstat.to_frame(ctx.raw_latest(RAW_KJONN)))
    return ctx.sql(f"""
        select
            yrke                     as yrke,
            lower(kjonn_label)       as kjonn,
            tid                      as kvartal,
            lower(contentscode)      as variabel,
            cast(value as double)    as verdi
        from _kjonn
        where value is not null
          and lower(contentscode) in ({_FILTER_KJONN})
        order by yrke, kjonn, variabel
    """)


@model(
    name="clean.yrke_alder",
    deps=[f"raw:{RAW_ALDER}"],
    checks=[
        "unique:yrke,aldersgruppe",
        "not_null:lonnstakere",
        "aldersgruppe in ('0-39', '40-54', '55+')",
        "lonnstakere >= 0",
    ],
    doc="SSB 11658 delt på tre aldersbånd, siste kvartal. Antall lønnstakere.",
)
def clean_yrke_alder(ctx: Context) -> Any:
    ctx.register("_alder", jsonstat.to_frame(ctx.raw_latest(RAW_ALDER)))
    return ctx.sql("""
        select
            yrke                     as yrke,
            alder                    as aldersgruppe,
            tid                      as kvartal,
            cast(value as bigint)    as lonnstakere
        from _alder
        where value is not null
          and lower(contentscode) = 'lonsstakere'
        order by yrke, aldersgruppe
    """)


@model(
    name="clean.yrke_sykefravaer",
    deps=[f"raw:{RAW_SYKEFRAVAER}"],
    checks=[
        "unique:yrke,aar",
        "not_null:sykefravaer_pst",
        # Legemeldt sykefravær er en prosent av avtalte dagsverk. Over 30
        # prosent finnes ikke i noe yrke, og ville betydd at vi leser feil
        # statistikkvariabel.
        "sykefravaer_pst between 0 and 30",
    ],
    doc="SSB 14789, legemeldt sykefravær i prosent per yrke og år, begge kjønn.",
)
def clean_yrke_sykefravaer(ctx: Context) -> Any:
    ctx.register("_syk", jsonstat.to_frame(ctx.raw_latest(RAW_SYKEFRAVAER)))
    return ctx.sql("""
        select
            yrke                     as yrke,
            cast(tid as integer)     as aar,
            cast(value as double)    as sykefravaer_pst
        from _syk
        where value is not null
          and lower(contentscode) = 'sykefraversprosent'
        order by yrke, aar
    """)
