"""clean-laget for SSBs yrkesfordelte tabeller — 11658, 14789 og 11418.

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

* **Noen utsnitt er øyeblikksbilder, andre er hele serien.** Bestanden,
  medianlønna, kjønnsdelingen, snittalderen og arbeidstida hentes kvartal for
  kvartal tilbake til 2016; aldersbåndene og de kjønnsdelte lønnene bare for
  siste kvartal. Skillet er ikke prinsipielt, det er hva figurene trenger: en
  tidslinje leseren kan dra i krever en serie bak hvert lag den fargelegger.

Yrkeskoden er den samme STYRK-08-koden i alle tre tabellene, så de kobler
rett på hverandre og på ``clean.styrk``.

**Tabell 11418 er en reserve for kvartalsserien, ikke en egen målestørrelse.**
Kvartalstabellen (11658) undertrykker medianlønn langt oftere enn den årlige
(11418) gjør — samme yrke kan mangle tallet i ni av ti kvartaler og likevel
ha det i seks av ti år, fordi SSBs konfidensialitetsvurdering ikke gir
samme svar i de to tabellene. Se ``clean.yrke_lonn_aar`` og
``mart.arbeidsmarked_yrke_aar`` for hvordan reserven brukes: bare til å
fylle et hull tidslinja ellers ville skravert, aldri i stedet for et tall
kvartalsserien faktisk har.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_KVARTAL: Final[str] = "ssb/11658_kvartal"
RAW_LONN_KVARTAL: Final[str] = "ssb/11658_lonn_kvartal"
RAW_SISTE: Final[str] = "ssb/11658_siste"
RAW_KJONN: Final[str] = "ssb/11658_kjonn"
RAW_KJONN_KVARTAL: Final[str] = "ssb/11658_kjonn_kvartal"
RAW_ALDER: Final[str] = "ssb/11658_alder"
RAW_TREKK_KVARTAL: Final[str] = "ssb/11658_trekk_kvartal"
RAW_SYKEFRAVAER: Final[str] = "ssb/14789_sykefravaer"
RAW_LONN_AAR: Final[str] = "ssb/11418_lonn_aar"

# Statistikkvariablene vi henter fra 11658. Lista står her, ikke bare i
# ingest-funksjonen, fordi den er kontrakten clean-laget kontrollerer mot.
VARIABLER: Final[tuple[str, ...]] = (
    "Lonsstakere",  # antall personer med jobben som hovedarbeidsforhold
    "MedianMndLonn",  # median månedslønn, kroner
    "GjsnAlder",  # gjennomsnittsalder, år
    "GjAvtArbtid",  # gjennomsnittlig avtalt arbeidstid, timer per uke
)
VARIABLER_KJONN: Final[tuple[str, ...]] = ("Lonsstakere", "MedianMndLonn")

# Variablene som beskriver hvem som har yrket, ikke hvor mange. Hentes
# over hele serien, ikke bare siste kvartal, fordi tidslinja i sida lar
# leseren stille dem tilbake i tid. Se moduldocstringen til
# ``mart.arbeidsmarked_yrke_aar``.
VARIABLER_TREKK: Final[tuple[str, ...]] = ("GjsnAlder", "GjAvtArbtid")

_FILTER = ", ".join(f"'{code.lower()}'" for code in VARIABLER)
_FILTER_KJONN = ", ".join(f"'{code.lower()}'" for code in VARIABLER_KJONN)
_FILTER_TREKK = ", ".join(f"'{code.lower()}'" for code in VARIABLER_TREKK)


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
    name="clean.yrke_kjonn_kvartal",
    deps=[f"raw:{RAW_KJONN_KVARTAL}"],
    checks=[
        "unique:yrke,kjonn,kvartal",
        "kjonn in ('kvinner', 'menn')",
        "lonnstakere >= 0",
        "regexp_matches(kvartal, '^[0-9]{4}K[1-4]$')",
    ],
    doc="SSB 11658 delt på kjønn, hele kvartalsserien. Antall lønnstakere.",
)
def clean_yrke_kjonn_kvartal(ctx: Context) -> Any:
    """Kjønnsdelingen kvartal for kvartal.

    Samme utsnitt som ``clean.yrke_kjonn``, men over hele serien og bare med
    bestanden. Medianlønn per kjønn er ikke med: den trengs bare i
    øyeblikksbildet, og å ta den med hit ville doblet uttrekket uten at noe
    leser det.
    """
    ctx.register("_kjonn_kv", jsonstat.to_frame(ctx.raw_latest(RAW_KJONN_KVARTAL)))
    return ctx.sql("""
        select
            yrke                     as yrke,
            lower(kjonn_label)       as kjonn,
            tid                      as kvartal,
            cast(value as bigint)    as lonnstakere
        from _kjonn_kv
        where value is not null
          and lower(contentscode) = 'lonsstakere'
        order by yrke, kjonn, kvartal
    """)


@model(
    name="clean.yrke_trekk_kvartal",
    deps=[f"raw:{RAW_TREKK_KVARTAL}"],
    checks=[
        "unique:yrke,variabel,kvartal",
        f"variabel in ({_FILTER_TREKK})",
        # Ikke `> 0`. Se docstringen: kilden skriver 0 der det ikke er noen
        # å regne gjennomsnitt over.
        "verdi >= 0",
        "regexp_matches(kvartal, '^[0-9]{4}K[1-4]$')",
    ],
    doc="SSB 11658, gjennomsnittsalder og avtalt arbeidstid per yrke og kvartal.",
)
def clean_yrke_trekk_kvartal(ctx: Context) -> Any:
    """Snittalder og avtalt arbeidstid over hele serien.

    Den samme avveiningen som i ``clean.yrke_kjonn``, og med det samme
    svaret. Begge variablene er gjennomsnitt over personer som *har* yrket,
    og SSB skriver 0 der det ikke er noen igjen å regne over — 478 rader,
    fordelt likt på de to variablene, og alle sammen i de ti yrkene som har
    null lønnstakere i det kvartalet. En snittalder på null år er ikke en
    alder. Men det er kildens tall, og å tolke det er mart-lagets jobb.
    """
    ctx.register("_trekk", jsonstat.to_frame(ctx.raw_latest(RAW_TREKK_KVARTAL)))
    return ctx.sql(f"""
        select
            yrke                     as yrke,
            tid                      as kvartal,
            lower(contentscode)      as variabel,
            cast(value as double)    as verdi
        from _trekk
        where value is not null
          and lower(contentscode) in ({_FILTER_TREKK})
        order by yrke, variabel, kvartal
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


@model(
    name="clean.yrke_lonn_aar",
    deps=[f"raw:{RAW_LONN_AAR}"],
    checks=[
        "unique:yrke,aar",
        "not_null:yrke_navn",
        # Samme avveining som ellers i denne fila: kildens null beholdes som
        # null, men skulle den noen gang skrive 0 der det ikke er noen å
        # regne median for, er det mart-lagets jobb å tolke det, ikke clean.
        "median_lonn_arlig >= 0",
    ],
    doc="SSB 11418, median månedslønn per yrke og år (november, alle sektorer). Reserve for kvartalsserien.",
)
def clean_yrke_lonn_aar(ctx: Context) -> Any:
    """Årlig medianlønn — reserven for ``clean.yrke_lonn_kvartal``.

    Samme STYRK-08-kode, men en annen tabell med en annen
    konfidensialitetsvurdering: et yrke kan mangle medianlønn i ni av ti
    kvartaler i 11658 og likevel ha den i seks av ti år her. Referansen er
    november, ikke et kvartal, og tallet gjelder alle sektorer samlet — det
    er ikke den samme størrelsen kvartalsserien måler, bare en god nok
    tilnærming til å fylle et hull tidslinja ellers ville skravert. Se
    ``mart.arbeidsmarked_yrke_aar`` for bruken: bare som reserve, aldri i
    stedet for et tall kvartalsserien faktisk har.
    """
    ctx.register("_lonn_aar", jsonstat.to_frame(ctx.raw_latest(RAW_LONN_AAR)))
    return ctx.sql("""
        select
            yrke                     as yrke,
            yrke_label                as yrke_navn,
            cast(tid as integer)      as aar,
            cast(value as double)     as median_lonn_arlig
        from _lonn_aar
        where value is not null
          and lower(contentscode) = 'manedslonn'
        order by yrke, aar
    """)
