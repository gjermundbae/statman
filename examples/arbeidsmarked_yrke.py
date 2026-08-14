"""Ende-til-ende-eksempel: det norske arbeidsmarkedet, yrke for yrke.

Ekte tall fra SSB, hele veien fra API-kall til sakspakke. Kjeden er:

    klass.fetch_codes(7)      ->  raw/klass/styrk08_codes
    ssb.fetch_table(11658)    ->  raw/ssb/11658_kvartal, _siste, _kjonn, _alder
    ssb.fetch_table(14789)    ->  raw/ssb/14789_sykefravaer
      -> clean.styrk, clean.yrke_*
      -> mart.arbeidsmarked_yrke, mart.arbeidsmarked_hovedgruppe_kvartal
      -> output/arbeidsmarked_yrke/     (sakspakke)
      -> statman publish arbeidsmarked_yrke  -> docs/   (artikkel)

Saken er en flisefigur over 407 yrker, med seks lag å farge den etter.
Forbildet er Andrej Karpathys `karpathy.ai/jobs`, som gjør det samme for
USA — men der fire lag er BLS' *framskrivinger* og en språkmodells anslag
på hvor utsatt yrket er for KI, er alle seks lagene her målt. Det er ikke
en dyd i seg selv; det er bare det norske datagrunnlaget som tillater det.
SSB publiserer lønnstakere per fireside yrke hvert kvartal tilbake til
2016, og da trenger man ikke gjette hva teknologien vil gjøre med yrkene.
Man kan se hva den allerede gjorde.

Det egentlige arbeidet her er ikke flisene. Det er å vite hvilke yrker man
*ikke* kan regne tiårsvekst for — se ``statman/models/mart_arbeidsmarked.py``.

Kjør:  uv run statman example arbeidsmarked
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Final, NamedTuple

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, jsonstat, publish  # noqa: E402
from statman.models.clean_ssb_kpi import RAW_KPI, TOTALINDEKS  # noqa: E402
from statman.models.clean_ssb_yrke import (  # noqa: E402
    RAW_ALDER,
    RAW_KJONN,
    RAW_KVARTAL,
    RAW_LONN_KVARTAL,
    RAW_SISTE,
    RAW_SYKEFRAVAER,
    VARIABLER,
    VARIABLER_KJONN,
)
from statman.models.clean_styrk import RAW_STYRK  # noqa: E402
from statman.models.mart_arbeidsmarked import (  # noqa: E402
    BRUDD_FRA,
    BRUDD_TIL,
    MINSTE_YRKE,
    PERIODE_AAR,
    UTENFOR_HOVEDGRUPPE,
)
from statman.sources import klass, ssb  # noqa: E402

SLUG: Final[str] = "arbeidsmarked_yrke"
TABELL: Final[str] = "11658"
TABELL_SYKEFRAVAER: Final[str] = "14789"

# Publiseringsdatoen er en redaksjonell opplysning, ikke et tidsstempel.
# Se befolkningsvekst.py for hvorfor den settes for hånd.
PUBLISERT: Final[str] = "2026-08-13"

MODEL_YRKE: Final[str] = "mart.arbeidsmarked_yrke"
MODEL_GRUPPE: Final[str] = "mart.arbeidsmarked_hovedgruppe_kvartal"
MODEL_REALLONN: Final[str] = "mart.arbeidsmarked_reallonn_gruppe"
MODEL_KPI: Final[str] = "mart.konsumpris_kvartal"
MODELS: Final[list[str]] = [MODEL_YRKE, MODEL_GRUPPE, MODEL_REALLONN]

TABELL_KPI: Final[str] = "14700"

# Kodeverket hentes slik det gjaldt denne datoen. KLASS har ingen
# «nyeste»-variant, og en dato satt ved kjøretid ville gjort to hentinger
# uforlignbare — se statman/sources/klass.py.
STYRK_DATO: Final[str] = "2026-01-01"

METRICS: Final[tuple[str, ...]] = (
    "yrke_lonnstakere",
    "yrke_vekst_pst",
    "yrke_median_lonn",
    "yrke_kvinneandel",
    "yrke_gjennomsnittsalder",
    "yrke_sykefravaer",
    "yrke_avtalt_arbeidstid",
    "yrke_reallonn_vekst",
)

# Hvor mange yrker som navngis i topp- og bunnlista.
N_TOPP: Final[int] = 18

LENKE: Final[str] = "yrke"

# Reallønnsfiguren har hovedgrupper som merker, ikke yrker. Egen
# markeringsgruppe framfor å dele «yrke»: to velgere i samme gruppe ville
# styrt hverandre, og «Ledere» er ikke det samme som et yrke som heter det.
LENKE_GRUPPE: Final[str] = "hovedgruppe"

# Fargene i PNG-ene skal være de samme som i figurene sida tegner. Verdiene
# speiler fargerollene i statman/publish/assets/graf.css, der begrunnelsen
# og fargeblindhetsmålingene står.
FARGE_VEKST: Final[str] = "#2a9d5c"
FARGE_FALL: Final[str] = "#a33b32"
FARGE_KAT1: Final[str] = "#2b6ca3"
FARGE_KAT2: Final[str] = "#c07a2b"
FARGE_SKALA: Final[tuple[str, ...]] = ("#e4d8aa", "#deb77a", "#52aed0", "#4286c2", "#2e5ea5")
FARGE_MANGLER: Final[str] = "#c8c2b5"
FARGE_MANGLER_STREK: Final[str] = "#7d766a"


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent kodeverket og de fem utsnittene av SSBs yrkesstatistikk.

    Utsnittene er delt slik at hvert kall holder seg godt under SSBs grense
    på 150 000 celler, og slik at hvert av dem svarer på ett spørsmål:
    bestanden over tid, øyeblikksbildet, kjønnsdelingen, aldersdelingen og
    sykefraværet.
    """
    ssb.probe()
    written: dict[str, Path] = {
        RAW_STYRK: klass.fetch_codes(
            klass.STYRK08, date=STYRK_DATO, dataset=RAW_STYRK.partition("/")[2]
        )
    }

    utsnitt: tuple[tuple[str, str, dict[str, str]], ...] = (
        # Hele kvartalsserien, men bare bestanden: 583 × 42 celler.
        (RAW_KVARTAL, TABELL, {
            "Yrke": "*", "Kjonn": "0", "Alder": "999D",
            "ContentsCode": "Lonsstakere", "Tid": "*",
        }),
        # Øyeblikksbildet med alle fire variablene. TOP(1) framfor et
        # kvartal skrevet inn her, så hentingen følger med når SSB
        # publiserer neste kvartal.
        (RAW_SISTE, TABELL, {
            "Yrke": "*", "Kjonn": "0", "Alder": "999D",
            "ContentsCode": ",".join(VARIABLER), "Tid": "TOP(1)",
        }),
        (RAW_KJONN, TABELL, {
            "Yrke": "*", "Kjonn": "1,2", "Alder": "999D",
            "ContentsCode": ",".join(VARIABLER_KJONN), "Tid": "TOP(1)",
        }),
        (RAW_ALDER, TABELL, {
            "Yrke": "*", "Kjonn": "0", "Alder": "0-39,40-54,55+",
            "ContentsCode": "Lonsstakere", "Tid": "TOP(1)",
        }),
        # Hele lønnsserien. Trengs for reallønn, som må måles mellom to
        # kvartaler og ikke kan leses av øyeblikksbildet.
        (RAW_LONN_KVARTAL, TABELL, {
            "Yrke": "*", "Kjonn": "0", "Alder": "999D",
            "ContentsCode": "MedianMndLonn", "Tid": "*",
        }),
        (RAW_SYKEFRAVAER, TABELL_SYKEFRAVAER, {
            "Yrke": "*", "Kjonn": "0",
            "ContentsCode": "Sykefraversprosent", "Tid": "*",
        }),
        # Deflatoren. Bare totalindeksen; undergruppene trengs ikke.
        (RAW_KPI, TABELL_KPI, {
            "VareTjenesteGrp": TOTALINDEKS,
            "ContentsCode": "KpiIndMnd", "Tid": "*",
        }),
    )
    for ref, tabell, value_codes in utsnitt:
        written[ref] = ssb.fetch_table(
            tabell, value_codes=value_codes, dataset=ref.partition("/")[2]
        )
    return written


# --------------------------------------------------------------------------
# Presentasjon
# --------------------------------------------------------------------------
def _antall(verdi: float | None) -> str:
    if verdi is None:
        return "—"
    return f"{int(round(verdi)):,}".replace(",", " ")


def _kr(verdi: float | None) -> str:
    if verdi is None:
        return "ikke publisert"
    return f"{int(round(verdi)):,}".replace(",", " ") + " kr"


def _pst(verdi: float | None, *, fortegn: bool = True) -> str:
    if verdi is None:
        return "—"
    tall = f"{verdi * 100:+.1f}" if fortegn else f"{verdi * 100:.1f}"
    return (tall + " %").replace(".", ",")


def _andel(verdi: float | None) -> str:
    return _pst(verdi, fortegn=False)


def _aar(verdi: float | None) -> str:
    if verdi is None:
        return "—"
    return f"{verdi:.1f}".replace(".", ",") + " år"


def _timer(verdi: float | None) -> str:
    if verdi is None:
        return "—"
    return f"{verdi:.1f}".replace(".", ",") + " t"


def _fravaer(verdi: float | None) -> str:
    if verdi is None:
        return "ikke publisert"
    return f"{verdi:.1f}".replace(".", ",") + " %"


def _periode(rad: dict) -> str:
    """«2016K2 → 2026K2» blir «2016–2026»."""
    return f"{rad['kvartal_start'][:4]}–{rad['kvartal_slutt'][:4]}"


def _navneliste(df: pl.DataFrame, antall: int, *, synkende: bool) -> str:
    """«Sentralbordoperatører (-56,2 %), Førtrykkere (-47,4 %), …».

    Navnene hentes fra dataene og skrives ikke av for hånd. Skriver man dem
    av, står de igjen og lyver den dagen SSB reviderer et tall.
    """
    rader = df.sort("vekst_pst", descending=synkende).head(antall)
    return ", ".join(
        f"{rad['yrke_navn'].lower()} ({_pst(rad['vekst_pst'])})"
        for rad in rader.iter_rows(named=True)
    )


def _pp(verdi: float) -> str:
    """Prosentpoeng. Ikke prosent — differansen mellom to indekstall."""
    return f"{verdi:.1f}".replace(".", ",")


def _fallet(indeks: list[float]) -> tuple[int, int, int | None]:
    """Største sammenhengende fall i en indeks: (topp, bunn, gjenvunnet).

    Ikke «høyeste og laveste punkt» — de to ligger her i hver sin ende av
    serien, og ville sagt at reallønnen steg jevnt. Det den skal finne er
    det største *fallet*: toppen før nedturen, bunnen etter den, og det
    første punktet som passerer den gamle toppen igjen. ``None`` betyr at
    den ikke er passert ennå.
    """
    topp = bunn = 0
    lopende_topp = 0
    verste = 0.0
    for i, v in enumerate(indeks):
        if v > indeks[lopende_topp]:
            lopende_topp = i
        elif indeks[lopende_topp] - v > verste:
            verste = indeks[lopende_topp] - v
            topp, bunn = lopende_topp, i
    gjenvunnet = next(
        (i for i in range(bunn, len(indeks)) if indeks[i] > indeks[topp]), None
    )
    return topp, bunn, gjenvunnet


def _spenn_uten_minste(sivile: pl.DataFrame) -> float:
    """Spennet i indeks når den minste gruppa holdes utenfor.

    «Bønder, fiskere mv.» har åtte yrker og under 20 000 lønnstakere i
    vekten, og ligger alene halvannet poeng over de andre. Å oppgi spennet
    med og uten den er ærligere enn å velge én av dem.
    """
    uten = sivile.sort("lonnstakere_vekt").tail(sivile.height - 1)
    return float(uten["reallonn_indeks"].max() - uten["reallonn_indeks"].min())


def _reallonnsliste(df: pl.DataFrame, antall: int, *, synkende: bool) -> str:
    """Som :func:`_navneliste`, men på reallønn."""
    rader = df.sort("reallonn_vekst_pst", descending=synkende).head(antall)
    return ", ".join(
        f"{rad['yrke_navn'].lower()} ({_pst(rad['reallonn_vekst_pst'])})"
        for rad in rader.iter_rows(named=True)
    )


def _kvintiler(df: pl.DataFrame) -> dict[str, float]:
    """Vektet reallønnsvekst i laveste og høyeste lønnskvintil ved start.

    Inndelingen er et valg og gjøres her. Poenget den svarer på er om
    reallønnsveksten henger sammen med lønnsnivået man startet på — altså om
    forskjellene mellom yrker ble mindre eller større.
    """
    med = df.filter(pl.col("median_lonn_start").is_not_null())
    kvintil = med.with_columns(
        pl.col("median_lonn_start").qcut(5, labels=[str(i) for i in range(5)]).alias("_k")
    )
    vektet = (
        kvintil.group_by("_k")
        .agg(
            ((pl.col("reallonn_vekst_pst") * pl.col("lonnstakere")).sum()
             / pl.col("lonnstakere").sum()).alias("vekst")
        )["vekst"]
    )
    return {"lav": float(vektet.min()), "hoy": float(vektet.max())}


def _finn(df: pl.DataFrame, navn: str) -> int:
    """Antall lønnstakere i ett navngitt yrke.

    Slår opp framfor å skrive tallet av, så teksten følger dataene. Reiser
    hvis yrket ikke finnes — et navn som forsvinner fra standarden skal gi
    en feil her, ikke en tom setning i sakspakken.
    """
    treff = df.filter(pl.col("yrke_navn") == navn)
    if treff.height != 1:
        raise KeyError(f"fant {treff.height} yrker som heter {navn!r}, ventet ett")
    return int(treff["lonnstakere"][0])


# --------------------------------------------------------------------------
# Fargelagene — der inndelingene velges
# --------------------------------------------------------------------------
# Å plassere en verdi på et trinn er en inndeling, og en inndeling er et
# valg. Derfor står grensene her, i analysen, og ikke i rendereren. De er
# runde tall og ikke kvartiler med vilje: en leser skal kunne lese
# tegnforklaringen og vite hva hen ser på, uten å måtte vite hvordan
# fordelingen ser ut.
class Lag(NamedTuple):
    """Ett fargelag: hvilken kolonne, hvilke grenser, hvilke ord."""

    key: str
    label: str
    kolonne: str
    roller: tuple[str, ...]
    grenser: tuple[float, ...]
    tekster: tuple[str, ...]
    caption: str


LAG: Final[tuple[Lag, ...]] = (
    Lag(
        key="lonn",
        label="Median månedslønn",
        kolonne="median_lonn",
        roller=("skala1", "skala2", "skala3", "skala4", "skala5"),
        grenser=(40_000, 50_000, 60_000, 75_000),
        tekster=(
            "under 40 000 kr", "40–50 000 kr", "50–60 000 kr",
            "60–75 000 kr", "75 000 kr og over",
        ),
        caption="Median månedslønn omregnet til heltid. De store lyse flatene "
        "nederst til høyre — butikk, barnehage, renhold, pleie — er der de "
        "fleste jobber og der lønna er lavest. De mørkeste flisene er små.",
    ),
    Lag(
        key="vekst",
        label=f"Endring på {PERIODE_AAR} år",
        kolonne="vekst_pst",
        roller=("avvik1", "avvik2", "avvik3", "avvik4", "avvik5"),
        grenser=(-0.20, -0.05, 0.05, 0.25),
        tekster=(
            "ned over 20 %", "ned 5–20 %", "omtrent uendret",
            "opp 5–25 %", "opp over 25 %",
        ),
        caption="Målt endring i antall lønnstakere fra samme kvartal ti år før — "
        "ikke en framskriving. Yrker som ikke kan sammenlignes over ti år er "
        "skravert; se metodeavsnittet for hvilke og hvorfor.",
    ),
    Lag(
        key="reallonn",
        label="Reallønn på 10 år",
        kolonne="reallonn_vekst_pst",
        roller=("avvik1", "avvik2", "avvik3", "avvik4", "avvik5"),
        grenser=(-0.05, 0.0, 0.05, 0.10),
        tekster=(
            "ned over 5 %", "ned 0–5 %", "opp 0–5 %",
            "opp 5–10 %", "opp over 10 %",
        ),
        caption="Endring i medianlønn etter at prisveksten er trukket fra. "
        "Prisene steg 37 prosent i perioden, så en flis som er blå her har "
        "hatt lønnsvekst *utover* det. De aller fleste flatene ligger i de "
        "to midterste trinnene — reallønnsveksten er påfallende jevn.",
    ),
    Lag(
        key="kjonn",
        label="Kvinneandel",
        kolonne="kvinneandel",
        roller=("skala1", "skala2", "skala3", "skala4", "skala5"),
        grenser=(0.20, 0.40, 0.60, 0.80),
        tekster=("under 20 %", "20–40 %", "40–60 %", "60–80 %", "80 % og over"),
        caption="Fordelingen er blokker, ikke en glidende skala. Håndverk og "
        "transport er nesten uten kvinner; helse, omsorg og undervisning er "
        "nesten uten menn. De to blokkene ligger hver sin plass i figuren, og "
        "midtsjiktet er tynnere enn både størrelsen og antallet yrker skulle "
        "tilsi — se funnet over for tallene.",
    ),
    Lag(
        key="alder",
        label="Gjennomsnittsalder",
        kolonne="gjennomsnittsalder",
        roller=("skala1", "skala2", "skala3", "skala4", "skala5"),
        grenser=(38, 42, 45, 48),
        tekster=("under 38 år", "38–42 år", "42–45 år", "45–48 år", "48 år og over"),
        caption="Snittalderen i yrket i dag. Den sier hvem som er der nå, ikke "
        "hvem som slutter snart — et yrke folk kommer til sent i karrieren har "
        "høy snittalder uten å være i ferd med å tømmes.",
    ),
    Lag(
        key="sykefravaer",
        label="Sykefravær",
        kolonne="sykefravaer_pst",
        roller=("skala1", "skala2", "skala3", "skala4", "skala5"),
        grenser=(3.0, 4.5, 6.0, 7.5),
        tekster=("under 3 %", "3–4,5 %", "4,5–6 %", "6–7,5 %", "7,5 % og over"),
        caption="Legemeldt sykefravær i prosent av avtalte dagsverk, 2025. "
        "Egenmeldt fravær er ikke med. Tallet er ikke justert for alder eller "
        "kjønn, og en del av mønsteret her er nettopp det.",
    ),
    Lag(
        key="arbeidstid",
        label="Avtalt arbeidstid",
        kolonne="avtalt_arbeidstid",
        roller=("skala1", "skala2", "skala3", "skala4", "skala5"),
        grenser=(20, 30, 34, 36),
        tekster=(
            "under 20 t/uke", "20–30 t/uke", "30–34 t/uke",
            "34–36 t/uke", "36 t/uke og over",
        ),
        caption="Gjennomsnittlig avtalt arbeidstid per uke. Lyse flater er yrker "
        "der stillingene er små — som ikke er det samme som yrker der folk vil "
        "jobbe lite.",
    ),
)


def _trinn(lag: Lag, verdi: float | None) -> str:
    """Hvilken fargerolle en verdi havner på. Null blir «mangler»."""
    if verdi is None:
        return publish.article.TONE_MANGLER
    for i, grense in enumerate(lag.grenser):
        if verdi < grense:
            return lag.roller[i]
    return lag.roller[-1]


def _vekstrolle(rad: dict) -> str:
    """Vekstlaget skiller «ikke sammenlignbar» fra «ingen endring».

    Et yrke uten sammenlignbar tiårsserie har ikke vekst nær null — det har
    ingen vekst å vise. De to må se forskjellige ut, ellers leser figuren
    som om militæret sto stille.
    """
    if not rad["sammenlignbar"]:
        return publish.article.TONE_MANGLER
    return _trinn(LAG[1], rad["vekst_pst"])


def _roller(rad: dict) -> tuple[str, ...]:
    """Én fargerolle per lag, i lagenes rekkefølge."""
    return tuple(
        _vekstrolle(rad) if lag.key == "vekst" else _trinn(lag, rad[lag.kolonne])
        for lag in LAG
    )


# --------------------------------------------------------------------------
# Flisoppdeling — den samme som sida gjør, for PNG-en
# --------------------------------------------------------------------------
def _verst(rad: list[float], kant: float) -> float:
    if not rad:
        return math.inf
    s, mx, mn = sum(rad), max(rad), min(rad)
    if s <= 0 or mn <= 0:
        return math.inf
    return max(kant * kant * mx / (s * s), s * s / (kant * kant * mn))


def squarify(
    deler: list[tuple[float, Any]], x: float, y: float, b: float, h: float
) -> list[tuple[Any, float, float, float, float]]:
    """Squarified treemap etter Bruls, Huizing og van Wijk (2000).

    Samme algoritme som ``statman/publish/assets/graf.js``, fordi PNG-en og
    figuren sida tegner skal vise den samme oppdelingen. To implementasjoner
    av samme algoritme er en kostnad; to *forskjellige* figurer er verre.
    """
    igjen = [(v, nyttelast) for v, nyttelast in deler if v > 0]
    sum_verdi = sum(v for v, _ in igjen)
    if sum_verdi <= 0 or b <= 0 or h <= 0:
        return []
    skala = b * h / sum_verdi
    areal = [v * skala for v, _ in igjen]

    ut: list[tuple[Any, float, float, float, float]] = []
    p = 0
    while p < len(igjen):
        kant = min(b, h)
        rad: list[float] = []
        best = math.inf
        while p + len(rad) < len(igjen):
            kandidat = rad + [areal[p + len(rad)]]
            forhold = _verst(kandidat, kant)
            if not rad or forhold <= best:
                best, rad = forhold, kandidat
            else:
                break
        radsum = sum(rad)
        if b >= h:
            rb = radsum / h
            cy = y
            for i, a in enumerate(rad):
                ih = a / rb
                ut.append((igjen[p + i][1], x, cy, rb, ih))
                cy += ih
            x, b = x + rb, b - rb
        else:
            rh = radsum / b
            cx = x
            for i, a in enumerate(rad):
                ib = a / rh
                ut.append((igjen[p + i][1], cx, y, ib, rh))
                cx += ib
            y, h = y + rh, h - rh
        p += len(rad)
    return ut


def _grupper(df: pl.DataFrame) -> list[tuple[str, int, list[dict]]]:
    """Yrkene samlet i hovedgrupper, begge deler sortert på størrelse."""
    rader = [r for r in df.iter_rows(named=True) if r["lonnstakere"] > 0]
    bolker: dict[str, list[dict]] = {}
    for rad in rader:
        bolker.setdefault(rad["hovedgruppe_navn"], []).append(rad)
    ut = [
        (navn, sum(r["lonnstakere"] for r in barn),
         sorted(barn, key=lambda r: -r["lonnstakere"]))
        for navn, barn in bolker.items()
    ]
    ut.sort(key=lambda t: -t[1])
    return ut


# --------------------------------------------------------------------------
# Grafer
# --------------------------------------------------------------------------
def _plot_fliser(df: pl.DataFrame, path: Path, periode: str) -> Path:
    """Flisediagrammet som PNG, farget etter medianlønn — lag nummer én.

    PNG-en kan bare vise ett av de seks lagene. Den viser det første, og
    bildeteksten sier fra om at de fem andre finnes i figuren sida tegner.
    """
    B, H = 1180.0, 760.0
    # Skravurstreken er en global innstilling i matplotlib, ikke et argument
    # til hver flate. Den settes her og ikke i toppen av fila, så en annen
    # figur i samme kjøring ikke arver den.
    plt.rcParams["hatch.color"] = FARGE_MANGLER_STREK
    plt.rcParams["hatch.linewidth"] = 0.7
    fig, ax = plt.subplots(figsize=(13.1, 8.6))
    lag = LAG[0]

    # Utsnittet settes før noe tegnes, så tekst kan måles i dataenheter mens
    # figuren bygges. Et anslag på tegnbredde bommet med en faktor tre og lot
    # det lengste gruppenavnet renne ut over nabogruppa — så her måles det,
    # akkurat som getBBox gjør det i sida.
    ax.set_xlim(0, B)
    ax.set_ylim(0, H)
    tegner = fig.canvas.get_renderer()

    def bredde(tekst: str, storrelse: float, **stil) -> float:
        t = ax.text(0, 0, tekst, fontsize=storrelse, **stil)
        ramme = t.get_window_extent(renderer=tegner).transformed(ax.transData.inverted())
        t.remove()
        return float(ramme.width)

    grupper = _grupper(df)
    celler = squarify([(total, (navn, barn)) for navn, total, barn in grupper], 0, 0, B, H)
    for (navn, barn), gx, gy, gb, gh in celler:
        gx, gy, gb, gh = gx + 1.5, gy + 1.5, gb - 3, gh - 3
        # Både høyde og bredde må holde. Uten breddesjekken renner de lange
        # gruppenavnene ut over nabogruppa og legger seg oppå navnet dens.
        topp = 17 if gh > 52 and bredde(navn, 8.5, fontweight="bold") + 6 < gb else 0
        if topp:
            ax.text(gx + 2, H - (gy + 12), navn, fontsize=8.5, color="0.25",
                    fontweight="bold", va="baseline")
        for rad, x, y, b, h in squarify(
            [(r["lonnstakere"], r) for r in barn], gx, gy + topp, gb, max(0.0, gh - topp)
        ):
            mangler = rad[lag.kolonne] is None
            farge = (
                FARGE_MANGLER if mangler
                else FARGE_SKALA[lag.roller.index(_trinn(lag, rad[lag.kolonne]))]
            )
            # Skravur og ikke bare en grå flate, av samme grunn som i sida:
            # «ikke publisert» skal ikke kunne forveksles med en lav verdi.
            ax.add_patch(plt.Rectangle(
                (x, H - y - h), b, h, facecolor=farge,
                edgecolor="white", linewidth=0.6,
                hatch="///" if mangler else None,
            ))
            # Bare navn som faktisk får plass. En avkortet etikett ser ut
            # som et annet yrke.
            if b > 40 and h > 14 and bredde(rad["yrke_navn"], 6.4) + 6 < b:
                ax.text(x + 3, H - y - 11, rad["yrke_navn"], fontsize=6.4,
                        color="white", va="baseline")
        # Ramma tegnes alltid, også når gruppenavnet ikke fikk plass — ellers
        # ser de navnløse gruppene ut som en fortsettelse av nabogruppa.
        ax.add_patch(plt.Rectangle((gx - 1, H - gy - gh - 1), gb + 2, gh + 2,
                                   facecolor="none", edgecolor="0.72", linewidth=0.8))

    ax.set_xlim(0, B)
    ax.set_ylim(0, H)
    ax.axis("off")
    ax.set_title(
        f"Alle {df.filter(pl.col('lonnstakere') > 0).height} yrker i Norge, "
        "etter antall lønnstakere",
        loc="left", fontsize=15, fontweight="bold",
    )
    ax.set_title(f"{df['kvartal_slutt'][0]}. Flate = antall lønnstakere.",
                 loc="right", fontsize=9, color="0.35")

    merker = [plt.Rectangle((0, 0), 1, 1, facecolor=f) for f in FARGE_SKALA]
    merker.append(plt.Rectangle((0, 0), 1, 1, facecolor=FARGE_MANGLER, hatch="///"))
    ax.legend(merker, list(lag.tekster) + ["ikke publisert"], loc="upper left",
              bbox_to_anchor=(0, -0.01), ncol=6, frameon=False, fontsize=8.5,
              title="Median månedslønn", title_fontsize=9, alignment="left")

    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell {TABELL}, {periode}. Farge viser medianlønn; i "
             "figuren på nett kan de samme flisene farges etter fem andre mål.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_topp_bunn(sml: pl.DataFrame, path: Path, periode: str) -> Path:
    """Topp og bunn på tiårsvekst. Bare sammenlignbare yrker."""
    topp = sml.sort("vekst_pst", descending=True).head(N_TOPP)
    bunn = sml.sort("vekst_pst").head(N_TOPP).sort("vekst_pst", descending=True)

    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    for ax, del_df, tittel in (
        (axes[0], topp, f"Størst vekst — topp {N_TOPP}"),
        (axes[1], bunn, f"Størst nedgang — bunn {N_TOPP}"),
    ):
        verdier = del_df["vekst_pst"].to_list()
        posisjoner = list(range(len(verdier)))
        farger = [FARGE_VEKST if v >= 0 else FARGE_FALL for v in verdier]
        ax.barh(posisjoner, verdier, color=farger, height=0.72)
        ax.set_yticks(posisjoner, del_df["yrke_navn"].to_list(), fontsize=8.5)
        ax.invert_yaxis()
        ax.set_title(tittel, loc="left", fontsize=11)
        ax.axvline(0, color="0.3", linewidth=0.8)
        ax.grid(True, axis="x", alpha=0.25, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_formatter(lambda v, _: _pst(v, fortegn=False))

        # Antallet hører hjemme rett ved siden av prosenten: 174 prosent av
        # 1 100 er noe annet enn 20 prosent av 90 000.
        spenn = max(abs(min(verdier)), abs(max(verdier))) or 1.0
        for i, rad in enumerate(del_df.iter_rows(named=True)):
            v = rad["vekst_pst"]
            ax.text(v + (0.02 * spenn if v >= 0 else -0.02 * spenn), i,
                    _antall(rad["lonnstakere"]), va="center",
                    ha="left" if v >= 0 else "right", fontsize=7.5, color="0.35")
        ax.set_xlim(min(0, min(verdier)) * 1.35, max(0, max(verdier)) * 1.4)

    fig.suptitle(f"Yrkene som vokste og krympet mest, {periode}",
                 x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell {TABELL}. Tall ved siden av søylene er antall "
             f"lønnstakere i dag. Bare yrker med minst {_antall(MINSTE_YRKE)} "
             "lønnstakere i begge ender, og utenom militære yrker og uoppgitt.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _plot_hovedgrupper(
    gruppe: pl.DataFrame, path: Path, periode: str, kvartal: str
) -> Path:
    """De ti hovedgruppene, samme kvartal hvert år, indeksert til starten.

    Bare ett kvartal i året, av samme grunn som at veksten måles mellom to
    like kvartaler: sesongen er større enn utviklingen. Med alle 42
    kvartalene ble figuren en tegning av innhøstingen — «Bønder, fiskere
    mv.» svinger 30 prosent fram og tilbake hvert eneste år, og den
    sagtannen er det eneste øyet ser. Trenden lå der hele tiden, den var
    bare ikke synlig.
    """
    df = gruppe.filter(pl.col("kvartal").str.slice(4, 2) == kvartal[4:6]).sort("kvartal")
    kvartaler = df["kvartal"].unique().sort().to_list()
    fig, ax = plt.subplots(figsize=(12.5, 7))
    farger = plt.get_cmap("tab10")

    rangert = (
        df.filter(pl.col("kvartal") == kvartaler[-1])
        .sort("lonnstakere", descending=True)["hovedgruppe"].to_list()
    )
    for i, kode in enumerate(rangert):
        serie = df.filter(pl.col("hovedgruppe") == kode).sort("kvartal")
        verdier = serie["lonnstakere"].to_list()
        indeks = [v / verdier[0] * 100 for v in verdier]
        navn = serie["hovedgruppe_navn"][0]
        ax.plot(range(len(indeks)), indeks, linewidth=2.0, color=farger(i % 10),
                label=f"{navn}  ({_antall(verdier[-1])})")

    ax.axhline(100, color="0.35", linewidth=1.0, linestyle="--")
    # Ett merke per punkt: med bare ett kvartal i året er det elleve av dem,
    # og da er det plass til årstallet uten å rotere det.
    ax.set_xticks(range(len(kvartaler)), [k[:4] for k in kvartaler], fontsize=9)
    ax.set_ylabel(f"Indeks, {kvartaler[0]} = 100")
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left",
              bbox_to_anchor=(1.01, 1.02), title="Hovedgruppe (lønnstakere i dag)",
              title_fontsize=9, alignment="left")
    ax.set_title(f"De ti hovedgruppene, {periode}", loc="left",
                 fontsize=15, fontweight="bold")
    ax.set_title(f"Målt i {kvartal[4:6].replace('K', '')}. kvartal hvert år.",
                 loc="right", fontsize=9, color="0.35")
    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell {TABELL}, summert opp fra de 407 yrkene. Ett "
             "kvartal i året, så sesongsvingninger ikke leses som utvikling.\n"
             "«Militære yrker og uoppgitt» er tatt med for å vise hva en "
             "omkoding gjør med en serie. Den linja er ikke en arbeidsmarkedsendring.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _reallonn_serie(gruppe: pl.DataFrame, kvartal: str) -> tuple[list[str], pl.DataFrame]:
    """Reallønnsindeksen, samme kvartal hvert år.

    Samme utvalg som resten av saken. Kvartalsserien har en sesongbølge på
    et par indekspoeng — lønn utbetales ikke jevnt gjennom året — og den er
    like stor som det ti år med reallønnsvekst utgjør. Med alle kvartaler
    ville figuren vist bonusutbetalinger.
    """
    df = gruppe.filter(pl.col("kvartal").str.slice(4, 2) == kvartal[4:6]).sort("kvartal")
    return df["kvartal"].unique().sort().to_list(), df


def _plot_reallonn(gruppe: pl.DataFrame, path: Path, periode: str, kvartal: str) -> Path:
    """Reallønnsindeks per hovedgruppe. Poenget er hvor lite de spriker."""
    kvartaler, df = _reallonn_serie(gruppe, kvartal)
    fig, ax = plt.subplots(figsize=(12, 7))

    etiketter: list[tuple[float, str]] = []
    for kode in sorted(df["hovedgruppe"].unique().to_list()):
        if kode == UTENFOR_HOVEDGRUPPE:
            continue  # militære yrker og uoppgitt: én yrkeskode, ikke en gruppe
        serie = df.filter(pl.col("hovedgruppe") == kode).sort("kvartal")
        alle = kode == "alle"
        ax.plot(
            range(len(kvartaler)), serie["reallonn_indeks"].to_list(),
            linewidth=3.0 if alle else 1.4,
            color=FARGE_KAT1 if alle else "0.55",
            alpha=1.0 if alle else 0.75,
            zorder=3 if alle else 2,
            label="Alle yrker" if alle else None,
        )
        if not alle:
            etiketter.append((
                serie["reallonn_indeks"].to_list()[-1],
                serie["hovedgruppe_navn"][0].removesuffix(" mv."),
            ))

    # Åtte linjer ender innenfor halvannet indekspoeng, så navnene legger seg
    # oppå hverandre. Vi skyver dem fra hverandre nedenfra og opp: sorter på
    # sluttverdi, og løft hver etikett til den har luft under seg.
    etiketter.sort()
    luft = (max(v for v, _ in etiketter) - min(v for v, _ in etiketter) or 1.0) * 0.16
    plassert: list[float] = []
    for verdi, _ in etiketter:
        plassert.append(verdi if not plassert else max(verdi, plassert[-1] + luft))
    for (verdi, navn), y in zip(etiketter, plassert):
        ax.annotate(
            navn, (len(kvartaler) - 1, verdi),
            xytext=(len(kvartaler) - 1 + 0.35, y), textcoords="data",
            fontsize=7.5, color="0.45", va="center",
            arrowprops={"arrowstyle": "-", "color": "0.78", "linewidth": 0.6,
                        "shrinkA": 0, "shrinkB": 2},
        )
    # Plass til de lengste gruppenavnene til høyre for siste punkt.
    ax.set_xlim(-0.4, len(kvartaler) + 4.4)

    ax.axhline(100, color="0.3", linewidth=1.0, linestyle="--")
    ax.set_xticks(range(len(kvartaler)), [k[:4] for k in kvartaler], fontsize=9)
    ax.set_ylabel(f"Reallønnsindeks, {kvartaler[0]} = 100")
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    # Ingen undertittel til høyre: der står gruppenavnene nå.
    ax.set_title("Ti år, ni yrkesgrupper, nesten samme reallønnsvekst",
                 loc="left", fontsize=14, fontweight="bold")
    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell {TABELL}, deflatert med KPI (tabell "
             f"{TABELL_KPI}). Målt i {kvartal[4:6].replace('K', '')}. kvartal "
             f"hvert år. Faste vekter fra {kvartaler[0]}, så indeksen måler "
             "lønnsendring og ikke at sammensetningen av yrker endret seg."
             "\nMilitære yrker og uoppgitt er utelatt: gruppa har bare én "
             "yrkeskode med komplett lønnsserie.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _graf_reallonn(gruppe: pl.DataFrame, kvartal: str, kilde: str) -> publish.Chart:
    """Reallønnslinjene, tegnet i sida."""
    kvartaler, df = _reallonn_serie(gruppe, kvartal)
    # Utsnittet regnes av de linjene som faktisk tegnes. Med hovedgruppe 0
    # med i regnestykket ble aksen skalert til en serie leseren ikke ser —
    # gruppa har én yrkeskode og svinger til 123 — og alle de ti linjene
    # klemte seg sammen i nederste tredjedel.
    tegnede = df.filter(pl.col("hovedgruppe") != UTENFOR_HOVEDGRUPPE)
    lav = float(tegnede["reallonn_indeks"].min())
    hoy = float(tegnede["reallonn_indeks"].max())

    merker = []
    for kode in sorted(df["hovedgruppe"].unique().to_list()):
        if kode == UTENFOR_HOVEDGRUPPE:
            continue
        serie = df.filter(pl.col("hovedgruppe") == kode).sort("kvartal")
        rader = list(serie.iter_rows(named=True))
        alle = kode == "alle"
        merker.append(publish.Mark(
            label=rader[0]["hovedgruppe_navn"],
            tone="kat1" if alle else "noytral",
            pin=alle,
            points=tuple((i, round(r["reallonn_indeks"], 2)) for i, r in enumerate(rader)),
            point_labels=tuple(
                f"{r['kvartal']} · {_indeks(r['reallonn_indeks'])}" for r in rader
            ),
            values=(
                publish.Readout(
                    f"Reallønn {periode_av(kvartaler)}",
                    _pst(rader[-1]["reallonn_indeks"] / 100 - 1),
                    "vekst" if rader[-1]["reallonn_indeks"] >= 100 else "fall",
                ),
                publish.Readout("Yrker i utvalget", str(rader[0]["yrker"])),
                publish.Readout("Vekt, lønnstakere", _antall(rader[0]["lonnstakere_vekt"])),
            ),
        ))

    return publish.Chart(
        kind="line",
        marks=tuple(merker),
        fallback="reallonn.png",
        alt="Ti linjer med reallønnsindeks per hovedgruppe, alle samlet i et "
        "smalt bånd rundt hundre.",
        x=publish.Axis(
            "", lo=-0.3, hi=len(kvartaler) - 0.7,
            ticks=tuple(range(len(kvartaler))),
            tick_labels=tuple(k[:4] for k in kvartaler),
        ),
        # Merkene utledes av utsnittet, ikke skrevet inn. Et merke utenfor
        # [lo, hi] tegnes der aksen ikke er, og havnet under x-etikettene.
        y=_indeksakse(f"← Reallønnsindeks, {kvartaler[0]} = 100", lav - 1.2, hoy + 1.2),
        guides=(publish.Guide("y", 100.0, ("samme kjøpekraft som i " + kvartaler[0][:4],)),),
        link=LENKE_GRUPPE,
        picker="Framhev yrkesgruppe",
        caption="Hver linje er én av hovedgruppene, med lønnsveksten deflatert "
        "med konsumprisindeksen. Vektene er låst til startkvartalet, så linja "
        "måler hva yrkene betaler og ikke at det ble flere av de godt betalte. "
        "Båndet er bemerkelsesverdig smalt: ti år, ni yrkesgrupper, og tre "
        "prosentpoeng mellom den øverste og den nederste — der den øverste er "
        "den minste gruppa i hele figuren.",
        source=kilde,
    )


def _indeksakse(etikett: str, lo: float, hi: float, steg: int = 2) -> publish.Axis:
    """En indeksakse med merker på runde tall *inni* utsnittet."""
    merker = tuple(
        v for v in range(int(math.ceil(lo / steg)) * steg, int(hi) + 1, steg)
    )
    return publish.Axis(
        label=etikett, lo=lo, hi=hi,
        ticks=merker, tick_labels=tuple(str(v) for v in merker),
    )


def periode_av(kvartaler: list[str]) -> str:
    return f"{kvartaler[0][:4]}–{kvartaler[-1][:4]}"


def _indeks(verdi: float) -> str:
    return f"{verdi:.1f}".replace(".", ",")


def _plot_lonn_kjonn(sml: pl.DataFrame, path: Path, periode: str) -> Path:
    """Kvinneandel mot medianlønn, én prikk per yrke."""
    df = sml.filter(pl.col("median_lonn").is_not_null())
    fig, ax = plt.subplots(figsize=(12, 7.5))
    ax.scatter(
        df["kvinneandel"].to_list(), df["median_lonn"].to_list(),
        s=[max(10.0, (n / 700) ** 0.85) for n in df["lonnstakere"].to_list()],
        c=[FARGE_VEKST if v >= 0 else FARGE_FALL for v in df["vekst_pst"].to_list()],
        alpha=0.55, linewidths=0,
    )
    for rad in _navngitte(df):
        ax.annotate(rad["yrke_navn"], (rad["kvinneandel"], rad["median_lonn"]),
                    textcoords="offset points", xytext=(7, 4), fontsize=8, color="0.2")

    ax.axvline(0.5, color="0.8", linewidth=0.9)
    ax.set_xlim(-0.03, 1.03)
    ax.xaxis.set_major_formatter(lambda v, _: _pst(v, fortegn=False))
    ax.yaxis.set_major_formatter(lambda v, _: _antall(v))
    ax.set_xlabel("Kvinneandel i yrket")
    ax.set_ylabel("Median månedslønn, kroner")
    ax.grid(True, alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Kvinneandel og lønn henger sammen — men ikke i en rett linje",
                 loc="left", fontsize=14, fontweight="bold")
    ax.set_title(f"{periode}. Flatestørrelse følger antall lønnstakere.",
                 loc="right", fontsize=9, color="0.35")
    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell {TABELL}. Grønt = yrket vokste på ti år, rødt = "
             "det krympet. Bare sammenlignbare yrker med publisert medianlønn.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _navngitte(df: pl.DataFrame) -> list[dict]:
    """Et fåtall navn i punktskyen: ytterpunktene, pluss de største yrkene."""
    kandidater: list[dict] = []
    for kolonne in ("kvinneandel", "median_lonn"):
        for synkende in (True, False):
            kandidater += df.sort(kolonne, descending=synkende).head(2).to_dicts()
    kandidater += df.sort("lonnstakere", descending=True).head(5).to_dicts()

    valgt: list[dict] = []
    for rad in kandidater:
        for satt in valgt:
            if (abs(rad["kvinneandel"] - satt["kvinneandel"]) < 0.07
                    and abs(rad["median_lonn"] - satt["median_lonn"]) < 6000):
                break
        else:
            valgt.append(rad)
    return valgt


def _plot_gruppe_kjonn(df: pl.DataFrame, path: Path, periode: str) -> Path:
    """Hovedgruppene delt i kvinner og menn."""
    gruppe = (
        df.group_by("hovedgruppe", "hovedgruppe_navn")
        .agg(pl.col("kvinner").sum(), pl.col("menn").sum(),
             pl.col("lonnstakere").sum())
        .with_columns((pl.col("kvinner") / pl.col("lonnstakere")).alias("andel"))
        .sort("andel")
    )
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    posisjoner = list(range(gruppe.height))
    kvinner = (gruppe["kvinner"] / 1000).to_list()
    menn = (gruppe["menn"] / 1000).to_list()
    ax.barh(posisjoner, kvinner, color=FARGE_KAT1, height=0.62, label="Kvinner")
    ax.barh(posisjoner, menn, left=kvinner, color=FARGE_KAT2, height=0.62, label="Menn")
    for i, andel in enumerate(gruppe["andel"].to_list()):
        ax.text(kvinner[i] + menn[i] + 8, i, _andel(andel), va="center",
                fontsize=8.5, color="0.35")

    ax.set_yticks(posisjoner, gruppe["hovedgruppe_navn"].to_list(), fontsize=9)
    ax.grid(True, axis="x", alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlabel("Tusen lønnstakere")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title("Hovedgruppene, delt i kvinner og menn", loc="left",
                 fontsize=13, fontweight="bold")
    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell {TABELL}, {periode}. Tallet til høyre er "
             "kvinneandelen i gruppa.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# Figurer som tegnes i sida
# --------------------------------------------------------------------------
def _avlesning(rad: dict) -> tuple[publish.Readout, ...]:
    """Det boblen viser. Ferdig formatert her, aldri i nettleseren."""
    if rad["sammenlignbar"]:
        vekst = publish.Readout(
            f"Endring {PERIODE_AAR} år", _pst(rad["vekst_pst"]),
            "vekst" if rad["vekst_pst"] > 0 else "fall" if rad["vekst_pst"] < 0 else "noytral",
        )
    else:
        vekst = publish.Readout(f"Endring {PERIODE_AAR} år", "ikke sammenlignbar")
    return (
        publish.Readout("Lønnstakere", _antall(rad["lonnstakere"])),
        publish.Readout("Median månedslønn", _kr(rad["median_lonn"])),
        vekst,
        publish.Readout("Kvinneandel", _andel(rad["kvinneandel"])),
        publish.Readout("Snittalder", _aar(rad["gjennomsnittsalder"])),
        publish.Readout("Sykefravær", _fravaer(rad["sykefravaer_pst"])),
        publish.Readout("Avtalt arbeidstid", _timer(rad["avtalt_arbeidstid"])),
    )


def _graf_fliser(df: pl.DataFrame, kilde: str) -> publish.Chart:
    """Flisediagrammet med seks lag. Sakens midtpunkt.

    Merk hva som *ikke* sendes: ingen farger, ingen piksler og ingen
    oppdeling. Analysen sier hvor stor en flate er og hvilken *rolle* den
    har i hvert lag; sida regner ut hvor på skjermen den havner.
    """
    med_flate = df.filter(pl.col("lonnstakere") > 0)
    rader = list(med_flate.iter_rows(named=True))
    roller = [_roller(rad) for rad in rader]

    # «Ikke publisert» står i tegnforklaringen bare i de lagene som faktisk
    # har hull. En forklaring på en farge ingen flis har, er én linje leseren
    # må lete etter og ikke finne.
    lag = tuple(
        publish.Layer(
            key=l.key, label=l.label,
            legend=tuple(zip(l.roller, l.tekster))
            + (((publish.article.TONE_MANGLER, "ikke publisert"),)
               if any(r[i] == publish.article.TONE_MANGLER for r in roller) else ()),
            caption=l.caption,
        )
        for i, l in enumerate(LAG)
    )
    merker = tuple(
        publish.Mark(
            label=rad["yrke_navn"],
            group=rad["hovedgruppe_navn"],
            size=float(rad["lonnstakere"]),
            tones=roller[i],
            values=_avlesning(rad),
            note=_antall(rad["lonnstakere"]),
        )
        for i, rad in enumerate(rader)
    )
    return publish.Chart(
        kind="treemap",
        marks=merker,
        fallback="fliser.png",
        alt=f"Flisediagram med {med_flate.height} yrker gruppert i ti "
        "hovedgrupper. Flaten til hver flis følger antall lønnstakere.",
        layers=lag,
        layer_label="Farg flisene etter",
        link=LENKE,
        picker="Framhev yrke",
        group_label="Avgrens til hovedgruppe",
        width="full",
        caption="Hver flis er ett av de 407 yrkene i SSBs yrkesstandard, og "
        "flaten følger antall lønnstakere. Flisene ligger fast når du bytter "
        "lag, så det samme yrket står på samme sted uansett hva fargen viser. "
        "Velg et yrke i nedtrekket for å finne det igjen i alle figurene på "
        "sida.",
        source=kilde,
    )


def _graf_rangstripe(sml: pl.DataFrame, kilde: str) -> publish.Chart:
    """Alle sammenlignbare yrker på én linje, rangert på tiårsvekst."""
    df = sml.sort("vekst_pst", descending=True)
    antall = df.height
    vokste = df.filter(pl.col("vekst_pst") > 0).height
    falt = df.filter(pl.col("vekst_pst") < 0).height

    merker = tuple(
        publish.Mark(
            label=rad["yrke_navn"],
            group=rad["hovedgruppe_navn"],
            tone="vekst" if rad["vekst_pst"] > 0 else "fall",
            values=(
                publish.Readout("Endring", _pst(rad["vekst_pst"]),
                                "vekst" if rad["vekst_pst"] > 0 else "fall"),
                publish.Readout("Lønnstakere nå", _antall(rad["lonnstakere"])),
                publish.Readout("For ti år siden", _antall(rad["lonnstakere_start"])),
            ),
            note=f"nr. {i + 1} av {antall}",
        )
        for i, rad in enumerate(df.iter_rows(named=True))
    )
    topp, bunn = df.row(0, named=True), df.row(-1, named=True)
    return publish.Chart(
        kind="strip",
        marks=merker,
        fallback="vekst_topp_bunn.png",
        alt=f"To liggende søylediagram: de {N_TOPP} yrkene som vokste mest og "
        f"de {N_TOPP} som krympet mest, i prosent.",
        x=publish.Axis(
            lo=0, hi=antall - 1, ticks=(0, antall - 1),
            tick_labels=(
                f"{topp['yrke_navn']} {_pst(topp['vekst_pst'])}",
                f"{bunn['yrke_navn']} {_pst(bunn['vekst_pst'])}",
            ),
        ),
        guides=(publish.Guide("x", vokste - 0.5, (f"{vokste} vokste", f"{falt} krympet")),),
        link=LENKE,
        caption=f"Alle {antall} sammenlignbare yrkene på én linje, rangert på "
        "endring over ti år. Det valgte yrket får en nål her også, så du ser "
        "med én gang om det er et ytterpunkt eller midt i flokken. Uten "
        f"JavaScript står de {N_TOPP} øverste og {N_TOPP} nederste med navn i "
        "stedet, som søyler — og der er antallet skrevet ved siden av "
        "prosenten med vilje, siden prosentvekst alene setter små yrker både "
        "til topps og til bunns.",
        source=kilde,
    )


def _graf_lonn_kjonn(sml: pl.DataFrame, kilde: str) -> publish.Chart:
    """Kvinneandel mot medianlønn. Samme tall som lonn_kjonn.png."""
    df = sml.filter(pl.col("median_lonn").is_not_null())
    storst = float(df["lonnstakere"].max())
    lav, hoy = float(df["median_lonn"].min()), float(df["median_lonn"].max())
    navngitt = {r["yrke_navn"] for r in _navngitte(df)}

    merker = tuple(
        publish.Mark(
            label=rad["yrke_navn"],
            group=rad["hovedgruppe_navn"],
            x=round(rad["kvinneandel"], 4),
            y=float(rad["median_lonn"]),
            size=round(math.sqrt(rad["lonnstakere"] / storst), 3),
            tone="vekst" if rad["vekst_pst"] > 0 else "fall",
            values=_avlesning(rad),
            note=_kr(rad["median_lonn"]),
            pin=rad["yrke_navn"] in navngitt,
        )
        for rad in df.iter_rows(named=True)
    )
    return publish.Chart(
        kind="scatter",
        marks=merker,
        fallback="lonn_kjonn.png",
        alt="Punktdiagram: kvinneandel langs x-aksen, median månedslønn langs "
        "y-aksen, én prikk per yrke.",
        x=publish.Axis("Kvinneandel i yrket →", lo=-0.03, hi=1.03,
                       ticks=(0, 0.25, 0.5, 0.75, 1.0),
                       tick_labels=("0 %", "25 %", "50 %", "75 %", "100 %")),
        y=publish.Axis("← Median månedslønn", lo=lav - 4000, hi=hoy + 4000,
                       ticks=(40_000, 60_000, 80_000, 100_000, 120_000),
                       tick_labels=tuple(_antall(v) for v in
                                         (40_000, 60_000, 80_000, 100_000, 120_000))),
        legend=(("vekst", "Yrket vokste på ti år"), ("fall", "Yrket krympet")),
        guides=(publish.Guide("x", 0.5, ("flere menn", "flere kvinner")),),
        link=LENKE,
        caption="Flaten følger antall lønnstakere. Skyen er ikke en rett "
        "nedoverbakke — de mannsdominerte yrkene ligger både øverst og nederst. "
        "Det som skiller seg ut er den tunge klyngen til høyre for midten: "
        "store, kvinnedominerte yrker på lav lønn. Pekeren treffer nærmeste "
        "yrke; du trenger ikke treffe prikken.",
        source=kilde,
    )


def _graf_gruppe(df: pl.DataFrame, kilde: str) -> publish.Chart:
    """Hovedgruppene delt i kvinner og menn. Klikk avgrenser figurene over."""
    gruppe = (
        df.group_by("hovedgruppe", "hovedgruppe_navn")
        .agg(pl.col("kvinner").sum(), pl.col("menn").sum(),
             pl.col("lonnstakere").sum(), pl.len().alias("yrker"))
        .with_columns((pl.col("kvinner") / pl.col("lonnstakere")).alias("andel"))
        .sort("andel", descending=True)
    )
    merker = tuple(
        publish.Mark(
            label=rad["hovedgruppe_navn"],
            segments=(("kat1", round(rad["kvinner"] / 1000, 1)),
                      ("kat2", round(rad["menn"] / 1000, 1))),
            note=_andel(rad["andel"]),
            values=(
                publish.Readout("Kvinneandel", _andel(rad["andel"])),
                publish.Readout("Kvinner", _antall(rad["kvinner"]), "kat1"),
                publish.Readout("Menn", _antall(rad["menn"]), "kat2"),
                publish.Readout("Yrker i gruppa", str(rad["yrker"])),
            ),
        )
        for rad in gruppe.iter_rows(named=True)
    )
    maks = float((gruppe["lonnstakere"] / 1000).max())
    return publish.Chart(
        kind="bars",
        marks=merker,
        fallback="hovedgruppe_kjonn.png",
        alt="Liggende søyler per hovedgruppe, delt i kvinner og menn.",
        x=publish.Axis("", lo=0, hi=maks * 1.06,
                       ticks=(0, 200, 400, 600, 800),
                       tick_labels=("0", "200", "400", "600", "800")),
        legend=(("kat1", "Kvinner"), ("kat2", "Menn")),
        link=LENKE,
        caption="Tusen lønnstakere per hovedgruppe, sortert på kvinneandel. "
        "Tallet til høyre er kvinneandelen. Klikk på en gruppe for å avgrense "
        "figurene over til den.",
        source=kilde,
    )


# --------------------------------------------------------------------------
# Artikkel
# --------------------------------------------------------------------------
def artikkel(
    df: pl.DataFrame,
    gruppe: pl.DataFrame,
    reallonn: pl.DataFrame,
    kpi: pl.DataFrame,
    proveniens: dict[str, str],
) -> publish.Article:
    """Sakspakken som struktur. Notatet og nettsida rendres begge fra denne."""
    sml = df.filter(pl.col("sammenlignbar"))
    utenfor = df.filter(~pl.col("sammenlignbar"))
    forste = df.row(0, named=True)
    periode = _periode(forste)
    kvartal = forste["kvartal_slutt"]
    kilde = f"Kilde: SSB tabell {TABELL}, {kvartal}."

    total = int(df["lonnstakere"].sum())
    total_start = int(df["lonnstakere_start"].sum())
    landsvekst = total / total_start - 1
    med_flate = df.filter(pl.col("lonnstakere") > 0).height

    vokste = sml.filter(pl.col("vekst_pst") > 0).height
    krympet = sml.filter(pl.col("vekst_pst") < 0).height
    storst = df.sort("lonnstakere", descending=True).row(0, named=True)

    # De ti største yrkene mot resten — konsentrasjonen er et funn i seg selv.
    ti_storste = int(df.sort("lonnstakere", descending=True).head(10)["lonnstakere"].sum())

    kvinnedominert = sml.filter(pl.col("kvinneandel") >= 0.8)
    mannsdominert = sml.filter(pl.col("kvinneandel") <= 0.2)
    i_midten = sml.filter(
        (pl.col("kvinneandel") > 0.4) & (pl.col("kvinneandel") < 0.6)
    )

    # Lønnsnivået i de to blokkene, vektet med hvor mange som jobber der.
    def vektet_lonn(d: pl.DataFrame) -> float:
        e = d.filter(pl.col("median_lonn").is_not_null())
        return float(
            (e["median_lonn"] * e["lonnstakere"]).sum() / e["lonnstakere"].sum()
        )

    funn = publish.Section(
        "Funn",
        (
            publish.Stats((
                publish.Stat(_antall(total), "Lønnstakere", f"i {med_flate} yrker"),
                publish.Stat(_pst(landsvekst), "Flere på ti år", periode),
                publish.Stat(str(krympet), "Yrker krympet",
                             f"av {sml.height} sammenlignbare"),
                publish.Stat(_andel(ti_storste / total), "Jobber i ti yrker",
                             f"av {med_flate}"),
            )),
            publish.Findings((
                f"Norge har {_antall(total)} lønnstakere fordelt på {med_flate} "
                f"yrker. Det er skjevt fordelt: de ti største yrkene alene "
                f"rommer {_andel(ti_storste / total)} av alle. Størst er "
                f"**{storst['yrke_navn']}** med {_antall(storst['lonnstakere'])}.",

                f"På ti år vokste antallet lønnstakere {_pst(landsvekst)}. "
                f"Av de {sml.height} yrkene som kan sammenlignes over perioden, "
                f"vokste {vokste} og {krympet} krympet.",

                "**Yrkene som krympet mest, er i stor grad de som ble "
                "digitalisert.** De ni nederste på lista er "
                f"{_navneliste(sml, 9, synkende=False)}. Dataene sier ikke "
                "hvorfor et yrke krymper, og de ni har neppe én felles "
                "forklaring. Men det er vanskelig å lese lista uten å se "
                "selvbetjente pumper, nettbaserte spørreundersøkelser, desktop "
                "publishing, e-post og digitale søknadsskjemaer i den. Uansett "
                "årsak er dette ikke en spådom om hva teknologi *kan* gjøre "
                "med et yrke — det er en måling av hva som faktisk skjedde.",

                f"Øverst står {_navneliste(sml, 6, synkende=True)}. Toppen må "
                "leses med ett forbehold: «Andre hjelpearbeidere» er en "
                "samlekategori og ikke et yrke med et innhold, så veksten der "
                "kan like gjerne være omkoding som nye jobber. De tydelige "
                "vinnerne er de neste — og størrelsesforholdet er verdt å "
                f"merke seg: {_antall(_finn(sml, 'Programvareutviklere'))} "
                "programvareutviklere, mot "
                f"{_antall(storst['lonnstakere'])} {storst['yrke_navn'].lower()}.",

                f"**Arbeidsmarkedet er kjønnsdelt, ikke gradert.** Bare "
                f"{i_midten.height} av {sml.height} yrker har mellom 40 og 60 "
                "prosent kvinner, og de rommer bare "
                f"{_andel(i_midten['lonnstakere'].sum() / sml['lonnstakere'].sum())} "
                f"av lønnstakerne. {kvinnedominert.height} yrker er minst 80 "
                f"prosent kvinner og {mannsdominert.height} er minst 80 prosent "
                "menn — til sammen "
                f"{_andel((kvinnedominert['lonnstakere'].sum() + mannsdominert['lonnstakere'].sum()) / sml['lonnstakere'].sum())} "
                "av alle lønnstakere i sammenlignbare yrker.",

                "Sammenhengen mellom kvinneandel og lønn er der, men den er "
                "ikke en rett linje. De mannsdominerte yrkene ligger både "
                f"øverst og nederst på lønn, med et vektet snitt på "
                f"{_kr(vektet_lonn(mannsdominert))}. De kvinnedominerte ligger "
                f"tettere samlet, på {_kr(vektet_lonn(kvinnedominert))}.",
            )),
            _graf_fliser(df, kilde),
        ),
    )

    ti_aar = publish.Section(
        "Ti år",
        (
            _graf_rangstripe(sml, kilde),
            publish.Figure(
                "hovedgrupper_tid.png",
                alt="Ti linjer, én per hovedgruppe, indeksert til 100 ved "
                "starten av perioden.",
                caption="Hovedgruppene, samme kvartal hvert år. Akademiske "
                "yrker vokser både mest og jevnest — og er samtidig den "
                "største gruppa, så det er der mest av veksten i hele "
                "arbeidsmarkedet ligger. Kontoryrkene er de eneste som er "
                "færre i dag enn i 2016. Linja som stuper er «Militære yrker "
                "og uoppgitt», og den er tatt med nettopp for å vise hvordan "
                "en omkoding ser ut når den ikke holdes utenfor: fallet på "
                "tjue prosent er spesialistordningen i Forsvaret og bedre "
                "yrkesregistrering, ikke jobber som forsvant. Serien er ellers "
                "vist ett kvartal i året — med alle 42 ble figuren en tegning "
                "av innhøstingen, siden bønder og fiskere svinger 30 prosent "
                "fram og tilbake hvert år.",
                source=f"Kilde: SSB tabell {TABELL}, summert opp fra de 407 "
                "yrkene. Indeksert til første måling.",
                width="full",
            ),
        ),
    )

    # --- Reallønn -------------------------------------------------------
    real = sml.filter(pl.col("reallonn_vekst_pst").is_not_null())
    real_ned = real.filter(pl.col("reallonn_vekst_pst") < 0)
    kvartaler, gserie = _reallonn_serie(reallonn, kvartal)
    alle_serie = gserie.filter(pl.col("hovedgruppe") == "alle").sort("kvartal")
    indeks = alle_serie["reallonn_indeks"].to_list()
    aar = [k[:4] for k in kvartaler]
    topp_i, bunn_i, igjen_i = _fallet(indeks)
    sivile = gserie.filter(
        (pl.col("kvartal") == kvartal)
        & (~pl.col("hovedgruppe").is_in([UTENFOR_HOVEDGRUPPE, "alle"]))
    )
    kpi_start = kpi.filter(pl.col("kvartal") == forste["kvartal_start"]).row(0, named=True)
    prisvekst = kpi.filter(pl.col("kvartal") == kvartal)["kpi"][0] / kpi_start["kpi"] - 1

    # Bruddkvartalet, målt framfor påstått. Brutto bevegelse i det ene
    # kvartalsskiftet mot brutto bevegelse over hele tiåret.
    brudd_sum = int(df["endring_bruddkvartal"].abs().sum())
    endring_sum = int(df["vekst_antall"].abs().sum())
    brudd_dominans = sml.filter(
        (pl.col("vekst_antall") != 0)
        & (pl.col("endring_bruddkvartal").abs() > pl.col("vekst_antall").abs() / 2)
    ).height

    reallonn_seksjon = publish.Section(
        "Reallønn",
        (
            publish.Stats((
                publish.Stat(_pst(prisvekst), "Prisvekst", periode),
                publish.Stat(_pst(indeks[-1] / 100 - 1), "Reallønn, alle yrker",
                             f"{aar[0]}–{aar[-1]}"),
                publish.Stat(str(real_ned.height), "Yrker med reallønnsfall",
                             f"av {real.height} målte"),
                publish.Stat(
                    _pp(float(sivile["reallonn_indeks"].max()
                              - sivile["reallonn_indeks"].min())),
                    "Prosentpoeng", "mellom øverste og nederste gruppe"),
            )),
            publish.Findings((
                f"Prisene steg {_pst(prisvekst)} på ti år. Medianlønna steg "
                "mer i nesten alle yrker — men ikke mye mer. For hele "
                f"utvalget er reallønnsveksten {_pst(indeks[-1] / 100 - 1)} "
                "over ti år, altså rundt en halv prosent i året.",

                f"**Reallønnen falt i {aar[bunn_i]} tilbake til der den "
                f"startet.** Indeksen toppet seg i {aar[topp_i]} på "
                f"{_indeks(indeks[topp_i])}, falt {_pp(indeks[topp_i] - indeks[bunn_i])} "
                f"poeng til {_indeks(indeks[bunn_i])} i {aar[bunn_i]} — "
                f"praktisk talt samme kjøpekraft som i {aar[0]}, sju år "
                "tidligere — og passerte den gamle toppen igjen først i "
                + (f"{aar[igjen_i]}." if igjen_i is not None else "har ennå ikke passert den."),

                "**Det mest oppsiktsvekkende er hvor likt det slo ut.** "
                f"Mellom den hovedgruppa som kom best ut og den som kom "
                "dårligst ut er det "
                f"{_pp(float(sivile['reallonn_indeks'].max() - sivile['reallonn_indeks'].min()))} "
                "prosentpoeng — etter ti år, og den øverste er den minste "
                f"gruppa av alle. Ser man bort fra den, er spennet "
                f"{_pp(_spenn_uten_minste(sivile))} poeng: ledere, "
                "renholdere, håndverkere og akademikere fikk i praksis "
                "samme reallønnsutvikling. Norsk lønnsdannelse er samordnet, "
                "og dette er hvordan det ser ut i tallene.",

                f"Det gjelder ikke hvert enkelt yrke: {real_ned.height} av "
                f"{real.height} hadde reallønnsfall, og de sysselsetter "
                f"{_andel(real_ned['lonnstakere'].sum() / real['lonnstakere'].sum())} "
                "av lønnstakerne. Størst fall: "
                f"{_reallonnsliste(real, 3, synkende=False)}. Størst vekst: "
                f"{_reallonnsliste(real, 3, synkende=True)}.",

                "Og det er ikke slik at de lavest lønte tok igjen de høyest "
                "lønte. Deler man yrkene i fem etter lønnsnivået i "
                f"{aar[0]}, ligger reallønnsveksten mellom "
                f"{_pst(_kvintiler(real)['lav'])} og "
                f"{_pst(_kvintiler(real)['hoy'])} i alle fem — uten noe "
                "mønster nedover eller oppover. Lønnsforskjellene mellom "
                "yrker er omtrent der de var.",
            )),
            _graf_reallonn(reallonn, kvartal, f"Kilde: SSB tabell {TABELL}, "
                           f"deflatert med KPI (tabell {TABELL_KPI})."),
        ),
    )

    lonn_kjonn = publish.Section(
        "Lønn og kjønn",
        (
            _graf_lonn_kjonn(sml, kilde),
            _graf_gruppe(df, kilde),
        ),
    )

    metode = publish.Section(
        "Metode",
        (
            publish.Findings((
                f"Kilde: SSB tabell {TABELL}, «{proveniens['label']}». SSB "
                f"oppdaterte tabellen {proveniens['updated'][:10]}; hentet "
                f"{proveniens['fetched_at'][:19]}Z, sha256 "
                f"{proveniens['sha256'][:12]}…. Sykefraværet kommer fra tabell "
                f"{TABELL_SYKEFRAVAER} og gjelder {df['sykefravaer_aar'].max()}, "
                "ikke siste kvartal — kildene har ikke samme frekvens.",

                f"Yrkesinndelingen er STYRK-08 på fireside nivå, hentet fra "
                f"SSBs klassifikasjonstjeneste KLASS slik den gjaldt "
                f"{STYRK_DATO}. Hovedgruppenavnene måtte komme derfra og ikke "
                f"fra tabellen: tabell {TABELL} slår sammen militære yrker og "
                "høyskoleyrker til én kode `3_01-03`, og lar dermed to av de "
                "ti hovedgruppene stå uten navn.",

                f"**Partisjonen er eksakt.** De 407 yrkene summerer seg til "
                f"{_antall(total)} lønnstakere, som er nøyaktig det SSB "
                f"publiserer på «Alle yrker» — og til {_antall(total_start)} i "
                "startkvartalet, som også stemmer på personen. Det er en sjekk "
                "på modellen, ikke en tilfeldighet, og den er grunnen til at "
                "flatene i flisediagrammet kan påstå å være helheten.",

                f"**Perioden er samme kvartal ti år fra hverandre**, "
                f"{forste['kvartal_start']} mot {forste['kvartal_slutt']}. "
                "Antall lønnstakere svinger systematisk gjennom året, så to "
                "vilkårlige kvartaler ville blandet sesong med utvikling.",

                f"**{utenfor.height} av de 407 yrkene er holdt utenfor "
                f"rangeringen** på vekst. Kravet er minst {_antall(MINSTE_YRKE)} "
                "lønnstakere i begge ender av perioden, og at yrket ikke ligger "
                f"i hovedgruppe 0. Det holder {_andel(sml['lonnstakere'].sum() / total)} "
                "av lønnstakerne inne. Terskelen er ikke det som avgjør noe: "
                "settes den til 100 i stedet for 500, kommer det til flere "
                "yrker uten at et eneste av funnene over endrer seg.",

                "Hovedgruppe 0 er «Militære yrker og uoppgitt», og ingen av "
                "delene tåler en tiårsserie. Forsvaret innførte "
                "spesialistordningen (OR/OF) i 2016, og omkodingen alene gir "
                "«Befal med sersjant grad» +365 prosent og «Offiserer fra "
                "fenrik og høyere grad» -51 prosent. «Uoppgitt» er ikke et "
                "yrke i det hele tatt, men de 7 634 som mangler yrkeskode — en "
                "gruppe som selv falt fra 19 565 fordi registreringen ble "
                "bedre. De 12 000 er fordelt ut på de andre yrkene, og trekker "
                "veksten deres opp med noen tideler hver.",

                "**Utvalget er lønnstakere, ikke sysselsatte.** Selvstendig "
                "næringsdrivende er ikke med, og det treffer ikke yrkene likt: "
                "bønder, fiskere, frisører, tannleger og advokater er "
                "systematisk underrepresentert, mens offentlig ansatte yrker er "
                "fullt dekket. Hovedgruppe «Bønder, fiskere mv.» står med "
                f"{_antall(df.filter(pl.col('hovedgruppe') == '6')['lonnstakere'].sum())} "
                "lønnstakere og er dermed en brøkdel av næringen.",

                f"{df.filter(pl.col('median_lonn').is_null()).height} yrker "
                "mangler medianlønn, fordi SSB ikke publiserer den for yrker "
                "med for få observasjoner. I åtte kjønnsdelte celler skriver "
                "kilden 0; de er gjort til null, fordi en median på null kroner "
                "ikke er en lønn, men det kilden skriver når det ikke er noen å "
                "regne median for. Flisene deres er skravert, ikke lyse.",

                f"**Reallønn er deflatert med KPI totalindeks** (SSB tabell "
                f"{TABELL_KPI}), til kroner i {kvartal}. Kvartalsindeksen er "
                "snittet av de tre månedene. Referansekvartalet flytter seg "
                "når SSB publiserer en ny måned, og hele serien flytter seg "
                "med den — derfor står det i figurteksten.",

                "Reallønnsindeksen per hovedgruppe bruker **faste vekter** "
                f"fra {forste['kvartal_start']}, og bare de yrkene som har "
                "publisert medianlønn i samtlige kvartaler. Med løpende "
                "vekter ville indeksen blandet sammen to ting: at yrkene "
                "betalte mer, og at det ble flere ansatte i de yrkene som "
                "betaler best. Det er det første den skal måle. Prisen er at "
                "de minste yrkene faller ut — det er de samme som mangler "
                "median.",

                f"**SSB merker tabellen med et brudd mellom {BRUDD_FRA} og "
                f"{BRUDD_TIL}**: kvalitetsforbedringer i yrkesrapporteringen "
                "ga «større endringer i tabellene med yrke», og store "
                "endringer mellom disse periodene «bør tolkes med "
                "forsiktighet». Det ligger midt i tiårsperioden, så vi har "
                f"målt det: {_antall(brudd_sum)} lønnstakere skiftet yrkeskode "
                f"i det ene kvartalsskiftet, mot {_antall(endring_sum)} over "
                f"hele tiåret — altså {_andel(brudd_sum / endring_sum)} av all "
                f"bevegelse i ett av 40 kvartaler. For {brudd_dominans} av de "
                f"{sml.height} sammenlignbare yrkene er skiftet alene større "
                "enn halve tiårsendringen. Kolonnen `endring_bruddkvartal` i "
                "CSV-en har tallet for hvert yrke.",

                "Funnene over tåler det, men ikke uendret. Måler man i "
                "stedet fra 2016K4 til 2024K4 — utenom bruddet — står de "
                "samme ni yrkene nederst, i samme rekkefølge, med fall som "
                "er 3 til 10 prosentpoeng mindre. Retningen er den samme, "
                "størrelsen er noe mindre. Det er derfor saken snakker om "
                "hvilke yrker som krympet, og ikke om nøyaktig hvor mye.",

                "**Yrkeskoden settes av arbeidsgiver i a-meldingen** og "
                "kontrolleres ikke mot faktiske arbeidsoppgaver. En stilling "
                "kan bytte kode uten at noen bytter jobb, og arbeidsinnholdet "
                "kan endres fullstendig uten at koden flytter seg. Det siste er "
                "verdt å ha i bakhodet gjennom hele saken: dette måler hvor "
                "mange som *heter* noe, ikke hva de gjør om dagene.",

                "Det som ikke er gjort: lønn er ikke fulgt over tid. Det ville "
                "krevd deflatering, og nominelle kroner fra to år kan ikke "
                "sammenlignes uten. Serien finnes i kilden, så saken kan "
                "utvides den dagen deflateringen er en delt funksjon og ikke en "
                "kopi til.",
            )),
            publish.Table(
                columns=("Hovedgruppe", "Yrker", "Lønnstakere", "Herav kvinner",
                         "Median månedslønn", f"Endring {periode}"),
                align=("left", "right", "right", "right", "right", "right"),
                rows=tuple(
                    (
                        rad["hovedgruppe_navn"],
                        str(rad["yrker"]),
                        _antall(rad["lonnstakere"]),
                        _andel(rad["kvinner"] / rad["lonnstakere"]),
                        _kr(rad["vektet_lonn"]),
                        _pst(rad["lonnstakere"] / rad["lonnstakere_start"] - 1),
                    )
                    for rad in _gruppetabell(df).iter_rows(named=True)
                ),
                caption="De ti hovedgruppene. Medianlønna er et snitt av "
                "yrkenes medianer vektet med antall lønnstakere — ikke medianen "
                "i gruppa, som ikke lar seg regne ut fra yrkesmedianer. "
                "Endringen for «Militære yrker og uoppgitt» er omkodingen "
                "beskrevet over, ikke en arbeidsmarkedsendring. Klikk på en "
                "kolonneoverskrift for å sortere.",
            ),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker=f"Arbeidsmarked · SSB tabell {TABELL}",
        title="Det norske arbeidsmarkedet, yrke for yrke",
        lead=(
            f"Alle {med_flate} yrker med lønnstakere i Norge, som flater etter "
            f"hvor mange som jobber i dem. Seks lag å farge dem etter, og alle "
            "seks er målt — ingen framskrivinger, ingen anslag. Det egentlige "
            "arbeidet i denne saken er ikke å tegne flisene, men å vite hvilke "
            "yrker man *ikke* kan regne ti års endring for."
        ),
        published=PUBLISERT,
        sections=(funn, ti_aar, reallonn_seksjon, lonn_kjonn, metode),
        caveats=METRICS,
        provenance={
            "Kilde": f"SSB tabell {TABELL} — {proveniens['label']}",
            "Oppdatert": proveniens["updated"][:10],
            "Hentet": proveniens["fetched_at"][:19] + "Z",
            "sha256": proveniens["sha256"],
            "Sykefravær": f"SSB tabell {TABELL_SYKEFRAVAER}, "
                          f"{df['sykefravaer_aar'].max()}",
            "Yrkesstandard": f"STYRK-08 via SSB KLASS 7, per {STYRK_DATO}",
            "Modeller": f"{MODEL_YRKE} · {MODEL_GRUPPE}",
            "Bygget": proveniens["bygget"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "alle 407 yrker, alle kolonner"),
            ("fliser.png", "flisediagrammet, farget etter medianlønn"),
            ("vekst_topp_bunn.png", f"topp og bunn {N_TOPP} på tiårsvekst"),
            ("hovedgrupper_tid.png", "de ti hovedgruppene kvartal for kvartal"),
            ("reallonn.png", "reallønnsindeks per hovedgruppe"),
            ("lonn_kjonn.png", "kvinneandel mot medianlønn"),
            ("hovedgruppe_kjonn.png", "hovedgruppene delt i kvinner og menn"),
        ),
    )


def _gruppetabell(df: pl.DataFrame) -> pl.DataFrame:
    """Hovedgruppene med vektet medianlønn. Vektingen er et valg, se teksten."""
    return (
        df.group_by("hovedgruppe", "hovedgruppe_navn")
        .agg(
            pl.len().alias("yrker"),
            pl.col("lonnstakere").sum(),
            pl.col("lonnstakere_start").sum(),
            pl.col("kvinner").sum(),
            ((pl.col("median_lonn") * pl.col("lonnstakere")).sum()
             / pl.col("lonnstakere").filter(pl.col("median_lonn").is_not_null()).sum()
             ).alias("vektet_lonn"),
        )
        .sort("lonnstakere", descending=True)
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    df = io.load(MODEL_YRKE)
    gruppe = io.load(MODEL_GRUPPE)
    reallonn = io.load(MODEL_REALLONN)
    kpi = io.load(MODEL_KPI)
    sml = df.filter(pl.col("sammenlignbar"))
    periode = _periode(df.row(0, named=True))

    # Proveniensen hentes fra byggeloggen, ikke ved å slå opp nyeste rådata
    # på nytt. Nyeste kan ha blitt en annen siden modellene ble bygget.
    bygg = io.read_manifest(MODEL_YRKE)
    raa = bygg["raw"][RAW_SISTE]
    versjon = io.raw_version_dir(RAW_SISTE, raa["version"])
    proveniens = {
        **jsonstat.header(io.raw_data_file(versjon)), **raa, "bygget": bygg["built_at"]
    }

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    df.sort(["lonnstakere", "yrke"], descending=[True, False]).write_csv(csv_path)

    figurer = [
        _plot_fliser(df, target / "fliser.png", periode),
        _plot_topp_bunn(sml, target / "vekst_topp_bunn.png", periode),
        _plot_hovedgrupper(gruppe, target / "hovedgrupper_tid.png", periode,
                           df["kvartal_slutt"][0]),
        _plot_reallonn(reallonn, target / "reallonn.png", periode,
                       df["kvartal_slutt"][0]),
        _plot_lonn_kjonn(sml, target / "lonn_kjonn.png", periode),
        _plot_gruppe_kjonn(df, target / "hovedgruppe_kjonn.png", periode),
    ]

    art = artikkel(df, gruppe, reallonn, kpi, proveniens)
    art.validate(target)
    return [
        csv_path,
        *figurer,
        publish.markdown.write(art, target / "notat.md"),
        art.write(target),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
