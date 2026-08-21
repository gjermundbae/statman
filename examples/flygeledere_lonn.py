"""Ende-til-ende-eksempel: lønn, lønnsendringer og arbeidsbelastning for flygeledere.

Ett yrke, STYRK-08 3154, ute av 407 i den store yrkessaken. Kjeden:

    klass.fetch_codes(7)          ->  raw/klass/styrk08_codes
    ssb.fetch_table(11658, ...)   ->  raw/ssb/11658_kvartal, _lonn_kvartal
    ssb.fetch_table(11418, ...)   ->  raw/ssb/11418_lonn_aar
    ssb.fetch_table(14700, ...)   ->  raw/ssb/14700_kpi
    eurocontrol.fetch_prb_norway(2020..2024) -> raw/eurocontrol/prb_norway_<år>
      -> clean.styrk, clean.yrke_kvartal, clean.yrke_lonn_kvartal,
         clean.yrke_lonn_aar, clean.konsumprisindeks,
         clean.eurocontrol_trafikk_norge, clean.eurocontrol_kapasitet
      -> mart.flygeledere_lonn, mart.flygeledere_bestand_siste,
         mart.eurocontrol_bodo_arbeidsbelastning, mart.eurocontrol_bemanning_2024
      -> output/flygeledere_lonn/     (sakspakke)
      -> statman publish flygeledere_lonn  -> docs/   (artikkel)

Rådataene til lønnsdelen er de samme uttrekkene ``examples/arbeidsmarked_yrke.py``
henter for alle 407 yrker — samme spørring, samme parametre, en ny
tidsstemplet kopi. Det er med vilje: å hente en smalere versjon under samme
datasettnavn ville flyttet «nyeste» for den store yrkessaken også. Se
``statman/models/mart_flygeledere.py`` for hvorfor yrket likevel trenger
egne mart-tabeller og ikke bare et filter på de eksisterende.

Saken skrives i lys av flygeledernes streik, som startet fredag formiddag
21. august 2026 etter brudd i meklingen mellom Norsk Flygelederforening
(NFF) og Spekter/Avinor Flysikring. Tallene her tar ikke stilling til hvem
som har rett i konflikten — de svarer bare på hva lønna har vært, og hvor
den ikke er målt.

**Arbeidsbelastning** er lagt til i lys av at NFFs uttalte konfliktgrunn
ikke er lønn, men arbeidstid — pauser, livsfasepolitikk og rammer for
instruktørvirksomhet. SSBs egne arbeidstidstall for yrket er sjekket og
forkastet (se Metode: for lite yrke, tallene er personvern-avrundet på en
måte som gjør dem ubrukelige). Det som faktisk finnes og holder mål, er
EUROCONTOLs/PRBs årlige overvåkingsrapport for Avinor Flysikring —
bemanning mot egen plan og trafikk per driftstime. Det måler ikke det
samme som NFF beskriver (vaktlengde, pauser), men er den nærmeste
offentlige, sammenlignbare arbeidsbelastningsindikatoren som finnes. Se
``statman/models/clean_eurocontrol_norge.py``.

Kjør:  uv run statman example flygeledere
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, publish  # noqa: E402
from statman.models.clean_ssb_kpi import RAW_KPI, TOTALINDEKS  # noqa: E402
from statman.models.clean_ssb_yrke import RAW_KVARTAL, RAW_LONN_AAR, RAW_LONN_KVARTAL  # noqa: E402
from statman.models.clean_styrk import RAW_STYRK  # noqa: E402
from statman.models.clean_eurocontrol_norge import YEARS as EUROCONTROL_YEARS  # noqa: E402
from statman.models.mart_flygeledere import KPI_REFERANSE_MAANED, YRKE  # noqa: E402
from statman.sources import eurocontrol, klass, ssb  # noqa: E402

SLUG: Final[str] = "flygeledere_lonn"

TABELL_KVARTAL: Final[str] = "11658"
TABELL_LONN_AAR: Final[str] = "11418"
TABELL_KPI: Final[str] = "14700"

STYRK_DATO: Final[str] = "2026-01-01"

MODEL_LONN: Final[str] = "mart.flygeledere_lonn"
MODEL_BESTAND: Final[str] = "mart.flygeledere_bestand_siste"
MODEL_BODO: Final[str] = "mart.eurocontrol_bodo_arbeidsbelastning"
MODEL_BEMANNING: Final[str] = "mart.eurocontrol_bemanning_2024"
MODELS: Final[list[str]] = [MODEL_LONN, MODEL_BESTAND, MODEL_BODO, MODEL_BEMANNING]

METRICS: Final[tuple[str, ...]] = (
    "flygeledere_median_lonn",
    "flygeledere_median_lonn_realt",
    "yrke_lonnstakere",
)

PUBLISERT: Final[str] = "2026-08-21"

# Lønnsoppgjøret partene forhandlet om, slik Spekter/Avinor har oppgitt det
# offentlig i forbindelse med meklingen — ikke SSB-tall, og ikke samme
# størrelse som SSBs median. Se Metode-seksjonen for hvorfor de to ikke kan
# leses som samme mål: Spekters tall er et snitt per 31.3.2026, SSBs er en
# median for hele kvartalet, og bare det ene av Spekters to tall holder
# overtid utenfor slik SSB gjør.
SPEKTER_FAST_AARSLONN: Final[float] = 1_517_385.0
SPEKTER_TOTAL_AARSLONN: Final[float] = 1_658_755.0
SPEKTER_DATO: Final[str] = "2026-03-31"
FRONTFAG_TILLEGG: Final[float] = 62_000.0

FARGE_AARLIG: Final[str] = "#2b6ca3"
FARGE_KVARTAL: Final[str] = "#2a9d5c"
FARGE_SPEKTER: Final[str] = "#a33b32"
FARGE_KAPASITET: Final[str] = "#6a4c93"

AARLIG_TIL_OG_MED: Final[int] = 2020  # siste år i den sammenhengende, tidlige strekningen

# EUROCONTOLs kilde skriver «Bodo», uten ø — engelsk rapport, ikke norsk stedsnavn.
# Norsk stavemåte hører til presentasjonen, ikke til dataene selskapet selv publiserer.
ACC_VISNINGSNAVN: Final[dict[str, str]] = {
    "Bodo": "Bodø ACC", "Oslo": "Oslo ACC", "Stavanger": "Stavanger ACC",
}


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent kodeverket, de fire SSB-utsnittene og de fem EUROCONTROL-rapportene.

    SSB-spørringene er de samme som ``examples/arbeidsmarked_yrke.py`` bruker
    for de samme fire datasettene — se moduldocstringen for hvorfor de ikke
    innsnevres til ett yrke her. EUROCONTROL-rapportene er derimot allerede
    landsspesifikke (Norge/Avinor Flysikring) — én PDF per år, 2020-2024.
    """
    ssb.probe()
    written: dict[str, Path] = {
        RAW_STYRK: klass.fetch_codes(
            klass.STYRK08, date=STYRK_DATO, dataset=RAW_STYRK.partition("/")[2]
        )
    }
    written[RAW_KVARTAL] = ssb.fetch_table(
        TABELL_KVARTAL,
        value_codes={
            "Yrke": "*", "Kjonn": "0", "Alder": "999D",
            "ContentsCode": "Lonsstakere", "Tid": "*",
        },
        dataset=RAW_KVARTAL.partition("/")[2],
    )
    written[RAW_LONN_KVARTAL] = ssb.fetch_table(
        TABELL_KVARTAL,
        value_codes={
            "Yrke": "*", "Kjonn": "0", "Alder": "999D",
            "ContentsCode": "MedianMndLonn", "Tid": "*",
        },
        dataset=RAW_LONN_KVARTAL.partition("/")[2],
    )
    written[RAW_LONN_AAR] = ssb.fetch_table(
        TABELL_LONN_AAR,
        value_codes={
            "MaaleMetode": "01", "Yrke": "*", "Sektor": "ALLE",
            "Kjonn": "0", "AvtaltVanlig": "0",
            "ContentsCode": "Manedslonn", "Tid": "*",
        },
        dataset=RAW_LONN_AAR.partition("/")[2],
    )
    written[RAW_KPI] = ssb.fetch_table(
        TABELL_KPI,
        value_codes={"VareTjenesteGrp": TOTALINDEKS, "ContentsCode": "KpiIndMnd", "Tid": "*"},
        dataset=RAW_KPI.partition("/")[2],
    )
    for year in EUROCONTROL_YEARS:
        written[f"eurocontrol/{eurocontrol.dataset(year)}"] = eurocontrol.fetch_prb_norway(year)
    return written


# --------------------------------------------------------------------------
# Formatering
# --------------------------------------------------------------------------
def _kr(verdi: float) -> str:
    return f"{int(round(verdi)):,}".replace(",", " ") + " kr"


def _pst(verdi: float, *, fortegn: bool = True) -> str:
    tall = f"{verdi * 100:+.1f}" if fortegn else f"{verdi * 100:.1f}"
    return (tall + " %").replace(".", ",")


def _rad(df: pl.DataFrame, kilde: str, periode: str) -> dict:
    treff = df.filter((pl.col("kilde") == kilde) & (pl.col("periode") == periode))
    return treff.row(0, named=True)


# --------------------------------------------------------------------------
# Grafer — sida tegner samme tall selv, PNG-en er fallback
# --------------------------------------------------------------------------
def _plot_lonn(df: pl.DataFrame, kolonne: str, tittel: str, yetikett: str, path: Path) -> Path:
    """To atskilte streker — årlig og kvartalsvis — med luft der ingen kilde har tall.

    To ``ax.plot``-kall og ikke ett med et hull i punktlista: en polyline
    tegner rett linje mellom hvert par den får, uansett hvor langt unna de
    ligger på x-aksen. Skal 2021-2024 se ut som et hull og ikke en jevn
    stigning, må de to strekningene være to helt separate kall.
    """
    aarlig = df.filter((pl.col("kilde") == "aarlig") & (pl.col("aar") <= AARLIG_TIL_OG_MED)).sort("periode_x")
    kvartal = df.filter(pl.col("kilde") == "kvartalsvis").sort("periode_x")

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(aarlig["periode_x"], aarlig[kolonne], "o-", color=FARGE_AARLIG, linewidth=2, markersize=5, label="Årlig (SSB 11418, november)")
    ax.plot(kvartal["periode_x"], kvartal[kolonne], "o-", color=FARGE_KVARTAL, linewidth=2, markersize=5, label="Kvartalsvis (SSB 11658)")

    ax.axvspan(AARLIG_TIL_OG_MED + 10 / 12, 2025 + 7 / 12, color="0.9", zorder=0)
    ax.text((AARLIG_TIL_OG_MED + 2025) / 2 + 0.4, ax.get_ylim()[0], "  ikke publisert\n  for flygeledere",
            fontsize=8.5, color="0.4", va="bottom", ha="center")

    ax.set_ylabel(yetikett)
    ax.set_xlim(2014.6, 2026.7)
    ax.set_xticks(range(2015, 2027))
    ax.grid(True, alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    ax.set_title(tittel, loc="left", fontsize=14, fontweight="bold")
    fig.text(0.01, 0.005,
             "Kilde: SSB tabell 11418 og 11658, yrke 3154. Feltet markerer 2021-2024, der "
             "ingen av de to kildene publiserer medianlønn for flygeledere.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_oppgjor(kvartal: pl.DataFrame, path: Path) -> Path:
    """De tre eneste publiserte kvartalene, mot tallene fra lønnsoppgjøret."""
    kv = kvartal.sort("periode_x")
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(kv["periode_x"], kv["median_lonn_nominell"], "o-", color=FARGE_KVARTAL,
            linewidth=2.2, markersize=7, label="SSB, median månedslønn (kvartal)", zorder=3)

    for verdi, tekst in (
        (SPEKTER_FAST_AARSLONN / 12, "Spekter/Avinor: snitt fast årslønn ÷ 12"),
        (SPEKTER_TOTAL_AARSLONN / 12, "Spekter/Avinor: snitt inkl. tillegg og overtid ÷ 12"),
    ):
        ax.axhline(verdi, color=FARGE_SPEKTER, linewidth=1.2, linestyle="--", alpha=0.8)
        ax.text(kv["periode_x"].max() + 0.02, verdi, f" {tekst}\n {_kr(verdi)}",
                fontsize=8, color=FARGE_SPEKTER, va="center")

    ax.set_ylabel("Kroner per måned")
    ax.set_xticks(kv["periode_x"].to_list(), kv["periode"].to_list())
    ax.set_xlim(kv["periode_x"].min() - 0.15, kv["periode_x"].max() + 1.1)
    ax.grid(True, axis="y", alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title("De eneste tre kvartalene SSB har publisert", loc="left", fontsize=13, fontweight="bold")
    fig.text(0.01, 0.005,
             f"Kilde: SSB tabell 11658 (median, ekskl. overtid). Spekter/Avinors tall er snitt per "
             f"{SPEKTER_DATO}, oppgitt i forbindelse med meklingen — ikke SSB-tall, og ikke\n"
             "nødvendigvis samme mål. Se Metode.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_bodo_produktivitet(df: pl.DataFrame, path: Path) -> Path:
    """Bodø ACC, IFR-bevegelser per sektor-åpningstime — samme hull-teknikk som lønnsfiguren.

    2022 mangler et tall for Bodø i kilden (den rapporten nevner bare Oslo
    ACC med et konkret tall) — se ``clean.eurocontrol_kapasitet``. To
    ``ax.plot``-kall, ikke ett med et hull i punktlista, av samme grunn som
    i ``_plot_lonn``: en polyline ville tegnet en rett strek over 2022 som
    om tallet var kjent der.
    """
    d = df.filter(pl.col("bodo_ifr_per_sektortime").is_not_null()).sort("aar")
    forste = d.filter(pl.col("aar") <= 2021)
    andre = d.filter(pl.col("aar") >= 2023)

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(forste["aar"], forste["bodo_ifr_per_sektortime"], "o-", color=FARGE_KAPASITET,
            linewidth=2, markersize=6, label="Bodø ACC")
    ax.plot(andre["aar"], andre["bodo_ifr_per_sektortime"], "o-", color=FARGE_KAPASITET,
            linewidth=2, markersize=6)

    ax.axvspan(2021.5, 2022.5, color="0.9", zorder=0)
    ax.text(2022, ax.get_ylim()[0], "  ikke oppgitt\n  for Bodø i 2022",
            fontsize=8.5, color="0.4", va="bottom", ha="center")

    ax.set_ylabel("IFR-bevegelser per sektor-åpningstime")
    ax.set_xlim(2019.6, 2024.6)
    ax.set_xticks(range(2020, 2025))
    ax.grid(True, alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    ax.set_title("Bodø-kontrollen styrer mer trafikk per driftstime", loc="left", fontsize=14, fontweight="bold")
    fig.text(0.01, 0.005,
             "Kilde: EUROCONTROL/PRB Annual Monitoring Report, Norge, 2020-2024. Bodø ACC er "
             "kontrollsentralen med mest sammenhengende rapportering i disse dataene — ikke\n"
             "nødvendigvis representativ for Oslo og Stavanger ACC. Feltet markerer 2022, der "
             "rapporten ikke oppgir tallet for Bodø.",
             fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# Figurer sida tegner selv
# --------------------------------------------------------------------------
def _chart_lonn(df: pl.DataFrame, kolonne: str, fallback: str, y_lo: float, y_hi: float,
                 y_ticks: tuple[int, ...], alt: str, caption: str) -> publish.Chart:
    aarlig = df.filter((pl.col("kilde") == "aarlig") & (pl.col("aar") <= AARLIG_TIL_OG_MED)).sort("periode_x")
    kvartal = df.filter(pl.col("kilde") == "kvartalsvis").sort("periode_x")

    def merke(rader: pl.DataFrame, navn: str) -> publish.Mark:
        return publish.Mark(
            label=navn,
            tone="kat1" if navn.startswith("Årlig") else "vekst",
            pin=True,
            points=tuple((float(r["periode_x"]), round(float(r[kolonne]))) for r in rader.iter_rows(named=True)),
            point_labels=tuple(f"{r['periode']} · {_kr(r[kolonne])}" for r in rader.iter_rows(named=True)),
        )

    return publish.Chart(
        kind="line",
        marks=(merke(aarlig, "Årlig (SSB 11418, november)"), merke(kvartal, "Kvartalsvis (SSB 11658)")),
        fallback=fallback,
        alt=alt,
        x=publish.Axis(
            "", lo=2014.6, hi=2026.7,
            ticks=tuple(float(a) for a in range(2015, 2027)),
            tick_labels=tuple(str(a) for a in range(2015, 2027)),
        ),
        y=publish.Axis(_y_etikett(kolonne), lo=y_lo, hi=y_hi,
                        ticks=tuple(float(t) for t in y_ticks),
                        tick_labels=tuple(_kr(t) for t in y_ticks)),
        caption=caption,
        source=f"SSB tabell 11418 og 11658, yrke {YRKE}.",
        width="full",
    )


def _y_etikett(kolonne: str) -> str:
    return "← Median månedslønn, nominelt" if kolonne == "median_lonn_nominell" \
        else f"← Median månedslønn, {KPI_REFERANSE_MAANED[:4]}-kroner"


def _chart_oppgjor(kvartal: pl.DataFrame) -> publish.Chart:
    kv = kvartal.sort("periode_x")
    merke = publish.Mark(
        label="SSB, median månedslønn",
        tone="vekst",
        pin=True,
        points=tuple((float(r["periode_x"]), round(float(r["median_lonn_nominell"]))) for r in kv.iter_rows(named=True)),
        point_labels=tuple(f"{r['periode']} · {_kr(r['median_lonn_nominell'])}" for r in kv.iter_rows(named=True)),
    )
    lo, hi = float(kv["periode_x"].min()) - 0.15, float(kv["periode_x"].max()) + 0.6
    return publish.Chart(
        kind="line",
        marks=(merke,),
        fallback="oppgjor.png",
        alt="Linjediagram med tre punkter — SSBs median de tre eneste publiserte kvartalene — "
        "og to horisontale linjer for Spekters oppgitte snittlønn.",
        x=publish.Axis(
            "", lo=lo, hi=hi,
            ticks=tuple(kv["periode_x"].to_list()),
            tick_labels=tuple(kv["periode"].to_list()),
        ),
        y=publish.Axis("Kroner per måned", lo=110_000, hi=142_000,
                        ticks=(110_000.0, 115_000.0, 120_000.0, 125_000.0, 130_000.0, 135_000.0, 140_000.0),
                        tick_labels=tuple(_kr(t) for t in (110_000, 115_000, 120_000, 125_000, 130_000, 135_000, 140_000))),
        guides=(
            publish.Guide("y", SPEKTER_FAST_AARSLONN / 12, ("Spekter/Avinor: snitt fast årslønn ÷ 12",)),
            publish.Guide("y", SPEKTER_TOTAL_AARSLONN / 12, ("Spekter/Avinor: snitt inkl. tillegg og overtid ÷ 12",)),
        ),
        caption="SSBs median holder overtid utenfor, akkurat som Spekters «fast årslønn». De to "
        "ligger likevel ikke like — en median er lavere enn et snitt i en høyreskjev "
        "fordeling, og de to tallene er ikke målt på samme dag eller med samme metode.",
        source=f"SSB tabell 11658. Spekter/Avinor, snitt per {SPEKTER_DATO}.",
        width="full",
    )


def _chart_bodo_produktivitet(df: pl.DataFrame) -> publish.Chart:
    """Samme hull-teknikk som ``_chart_lonn`` — to merker, ikke ett med et hull i punktlista."""
    d = df.filter(pl.col("bodo_ifr_per_sektortime").is_not_null()).sort("aar")
    forste = d.filter(pl.col("aar") <= 2021)
    andre = d.filter(pl.col("aar") >= 2023)

    def merke(rader: pl.DataFrame, navn: str) -> publish.Mark:
        return publish.Mark(
            label=navn,
            tone="kat1",
            pin=True,
            points=tuple(
                (float(r["aar"]), round(float(r["bodo_ifr_per_sektortime"]), 2))
                for r in rader.iter_rows(named=True)
            ),
            point_labels=tuple(
                f"{int(r['aar'])} · {r['bodo_ifr_per_sektortime']:.2f} bevegelser/time"
                for r in rader.iter_rows(named=True)
            ),
        )

    return publish.Chart(
        kind="line",
        marks=(merke(forste, "Bodø ACC, 2020-2021"), merke(andre, "Bodø ACC, 2023-2024")),
        fallback="bodo_produktivitet.png",
        alt="Linjediagram: IFR-bevegelser per sektor-åpningstime ved Bodø ACC, 2020-2024, "
        "med et hull i 2022 der tallet ikke er oppgitt.",
        x=publish.Axis(
            "", lo=2019.6, hi=2024.6,
            ticks=tuple(float(a) for a in range(2020, 2025)),
            tick_labels=tuple(str(a) for a in range(2020, 2025)),
        ),
        y=publish.Axis(
            "IFR-bevegelser per sektor-åpningstime", lo=5.0, hi=8.0,
            ticks=(5.0, 6.0, 7.0, 8.0),
            tick_labels=("5,0", "6,0", "7,0", "8,0"),
        ),
        caption="Bodø ACC er valgt fordi det er den eneste av de tre kontrollsentralene med "
        "tall for fire av fem år i denne kilden — ikke fordi den nødvendigvis er "
        "representativ for Oslo og Stavanger ACC. 2022 mangler et tall for Bodø.",
        source="EUROCONTROL/PRB Annual Monitoring Report, Norge, 2020-2024.",
        width="full",
    )


# --------------------------------------------------------------------------
# Artikkel
# --------------------------------------------------------------------------
def artikkel(
    lonn: pl.DataFrame,
    bestand: dict,
    bodo: pl.DataFrame,
    bemanning: pl.DataFrame,
    bygg: dict,
    bygg_eurocontrol: dict,
) -> publish.Article:
    siste_kv = _rad(lonn, "kvartalsvis", "2026K2")
    a2015, a2020, a2025 = (_rad(lonn, "aarlig", str(a)) for a in (2015, 2020, 2025))
    kv2025k4 = _rad(lonn, "kvartalsvis", "2025K4")

    nom_15_20 = a2020["median_lonn_nominell"] / a2015["median_lonn_nominell"] - 1
    real_15_20 = a2020["median_lonn_realt"] / a2015["median_lonn_realt"] - 1
    nom_20_25 = a2025["median_lonn_nominell"] / a2020["median_lonn_nominell"] - 1
    real_20_25 = a2025["median_lonn_realt"] / a2020["median_lonn_realt"] - 1
    nom_15_25 = a2025["median_lonn_nominell"] / a2015["median_lonn_nominell"] - 1
    real_15_25 = a2025["median_lonn_realt"] / a2015["median_lonn_realt"] - 1
    kpi_15_25 = a2025["kpi_referanse"] / a2015["kpi_referanse"] - 1
    avvik_kilder = kv2025k4["median_lonn_nominell"] / a2025["median_lonn_nominell"] - 1

    lonn_seksjon = publish.Section(
        "Lønna",
        (
            publish.Stats((
                publish.Stat(_kr(siste_kv["median_lonn_nominell"]), "Median månedslønn nå", "2026K2, SSB tabell 11658"),
                publish.Stat(str(bestand["lonnstakere"]), "Flygeledere i Norge", f"{bestand['kvartal']}, SSB tabell 11658"),
                publish.Stat(_pst(nom_15_25), "Nominell vekst, 2015→2025", "november til november, samme kilde"),
                publish.Stat("4 år", "Uten publisert medianlønn", "2021-2024, verken årlig eller kvartalsvis"),
            )),
            publish.Findings((
                "SSB publiserer ikke medianlønn for flygeledere i kvartalstabellen før 4. "
                "kvartal 2025 — samtlige 39 kvartaler før det er tomme i kildens eget svar. Den "
                "årlige reservetabellen dekker mer, men heller ikke den har noe for "
                "**2021, 2022, 2023 eller 2024**. Figuren under viser nøyaktig det: to "
                "strekninger med tall, og et fireårig felt uten noen.",
            )),
            _chart_lonn(
                lonn, "median_lonn_nominell", "lonn.png", 65_000, 135_000,
                (70_000, 85_000, 100_000, 115_000, 130_000),
                "Linjediagram: median månedslønn for flygeledere, 2015-2026, med et "
                "fireårig felt uten tall mellom 2021 og 2024.",
                "To kilder, aldri sammenslått til én linje: den årlige reserven (11418) "
                "til venstre, kvartalstabellen (11658) til høyre. Feltet mellom dem er ikke "
                "en tegnefeil — det er hva SSB faktisk har publisert for dette yrket.",
            ),
        ),
    )

    reallonn_seksjon = publish.Section(
        "Reallønn",
        (
            publish.Stats((
                publish.Stat(_pst(real_15_20), "Reallønn, 2015→2020", "november til november"),
                publish.Stat(_pst(real_20_25), "Reallønn, 2020→2025", "november til november"),
                publish.Stat(_pst(real_15_25), "Reallønn, 2015→2025", "hele strekningen, samme kilde"),
                publish.Stat(_pst(kpi_15_25), "Prisvekst, 2015→2025", "KPI totalindeks, november"),
            )),
            publish.Findings((
                f"Nominelt steg medianlønna {_pst(nom_15_20)} fra november 2015 til november "
                f"2020, godt over prisveksten i samme periode ({_pst(a2020['kpi_referanse'] / a2015['kpi_referanse'] - 1)}) "
                f"— en reallønnsvekst på {_pst(real_15_20)}. Fra 2020 til 2025 var det motsatt: "
                f"nominelt {_pst(nom_20_25)}, men prisene steg mer, og reallønna falt "
                f"{_pst(real_20_25)}. Over hele strekningen, 2015 til 2025, er nettoresultatet "
                f"likevel en realvekst på {_pst(real_15_25)} — drevet av den første halvdelen.",
                "**Ett forbehold veier tungt her.** SSB melder om et brudd i lønnsnivået i "
                "1. kvartal 2020: bedre rapportering fra arbeidsgiverne ga et generelt høyere "
                "målt nivå, ikke bare i enkeltnæringer. Det ligger midt i strekningen "
                "2015-2020, og betyr at noe av den sterke veksten der kan være bedre "
                "registrering snarere enn høyere lønn. Ingen del av dette tallgrunnlaget kan "
                "skille de to fra hverandre.",
                "Disse tallene hopper over de fire uregistrerte årene i midten. De sier hva "
                "som skjedde mellom to punkter, ikke noe om banen mellom dem — reallønna kan "
                "ha steget og falt flere ganger i mellomtiden uten at det vises her.",
            )),
            _chart_lonn(
                lonn, "median_lonn_realt", "reallonn.png", 90_000, 135_000,
                (95_000, 105_000, 115_000, 125_000),
                f"Linjediagram: median månedslønn for flygeledere i {KPI_REFERANSE_MAANED[:4]}-kroner, "
                "2015-2026, med samme firårige felt uten tall.",
                f"Samme to kilder som over, deflatert til {KPI_REFERANSE_MAANED[:4]}-kroner med KPI "
                "totalindeks. Realveksten var sterkere i første halvdel av perioden enn i andre — "
                "se forbeholdet om rapporteringsbruddet i 2020 før den forskjellen leses som en trend.",
            ),
        ),
    )

    oppgjor_seksjon = publish.Section(
        "Lønnsoppgjøret",
        (
            publish.Findings((
                "Flygelederne har streiket siden fredag formiddag 21. august 2026, etter "
                "brudd i meklingen mellom Norsk Flygelederforening (NFF) og Spekter/Avinor "
                "Flysikring. Partene er uenige om hva striden står om: **NFF sier den "
                "handler om arbeidstid** — pauser, livsfasepolitikk og rammer for "
                "instruktørvirksomhet, ikke lønn — og at flygeledere risikerer å stå i "
                "tjeneste 8 til 16 timer uten pause. **Spekter sier NFF avviste et "
                f"lønnstillegg på linje med frontfaget**, i snitt {_kr(FRONTFAG_TILLEGG)} per "
                "flygeleder, og krevde arbeidstidsendringer som ville økt bemanningsbehovet "
                "og kostnadene betydelig.",
                f"Spekter har oppgitt at flygeledere i snitt hadde {_kr(SPEKTER_FAST_AARSLONN)} "
                f"i fast årslønn og {_kr(SPEKTER_TOTAL_AARSLONN)} inkludert faste tillegg og "
                f"overtid, per {SPEKTER_DATO}. SSBs egen median for samme periode ligger noe "
                f"lavere — {_kr(kv2025k4['median_lonn_nominell'])} i 2025K4 — som ventet når "
                "den ene er en median og den andre et snitt, og de ikke er målt på nøyaktig "
                "samme dag eller med samme metode.",
            )),
            _chart_oppgjor(lonn.filter(pl.col("kilde") == "kvartalsvis")),
        ),
    )

    trafikk_2019 = bodo.filter(pl.col("aar") == 2019).row(0, named=True)["ifr_bevegelser_norge_1000"]
    trafikk_2024 = bodo.filter(pl.col("aar") == 2024).row(0, named=True)["ifr_bevegelser_norge_1000"]
    andel_2019 = trafikk_2024 / trafikk_2019
    ops_total = int(bemanning["atco_ops"].sum())
    plan_total = int(bemanning["atco_plan"].sum())

    arbeidsbelastning_seksjon = publish.Section(
        "Arbeidsbelastning",
        (
            publish.Stats(tuple(
                publish.Stat(
                    f"{int(r['atco_ops'])} av {int(r['atco_plan'])}",
                    f"{ACC_VISNINGSNAVN[r['acc']]} ({r['acc_kode']}), ATCO i tjeneste/plan",
                    "2024, EUROCONTROL/PRB",
                )
                for r in bemanning.sort("acc").iter_rows(named=True)
            )),
            publish.Findings((
                "NFFs uttalte konfliktgrunn er ikke lønn, men arbeidstid. SSBs egne "
                "arbeidstidstall for yrket holder ikke mål her — se Metode for hvorfor. Det "
                "som finnes og er sammenlignbart, er EUROCONTROL/PRBs årlige "
                "overvåkingsrapport for Avinor Flysikring: bemanning mot selskapets egen "
                "plan, og trafikk per driftstime. Ingen av delene måler det NFF konkret "
                "beskriver — vaktlengde og pauser — men begge sier noe om belastningen "
                f"rundt dem. I 2024 var alle tre kontrollsentraler bemannet under sin egen "
                f"plan: {ops_total} flygeledere i operativ tjeneste mot en plan på "
                f"{plan_total}.",
                f"Trafikken har samtidig tatt seg opp igjen etter pandemien: Norge hadde "
                f"{trafikk_2024:.0f}K IFR-bevegelser i 2024, {_pst(andel_2019 - 1)} fra "
                f"2019-nivået ({trafikk_2019:.0f}K). Ved Bodø ACC — kontrollsentralen med "
                "mest sammenhengende tall i denne kilden — har det gitt flere IFR-bevegelser "
                "per sektor-åpningstime i alle årene rapporten oppgir tallet, sammenlignet "
                "med 2019.",
            )),
            _chart_bodo_produktivitet(bodo),
        ),
    )

    metode = publish.Section(
        "Metode",
        (
            publish.Findings((
                f"Kilde: SSB tabell {TABELL_KVARTAL} (kvartalsvis medianlønn) og "
                f"{TABELL_LONN_AAR} (årlig reserve, november, alle sektorer), yrke {YRKE} — "
                f"«Flygeledere» i STYRK-08. Hentet {bygg['built_at'][:19]}Z.",
                "**Kvartalstabellen mangler medianlønn for flygeledere i alle 39 kvartaler "
                "2016K1-2025K3.** Kontrollert direkte mot rå json-stat2-svar, ikke et utslag "
                "av filtrering i denne saken: verdien er `null` i kildens eget svar. Den "
                "årlige reserven dekker 2015-2020 og 2025, men heller ikke den har noe for "
                "2021-2024 — det hullet er ikke fylt her, verken med et interpolert tall "
                "eller et gjentatt tall fra et naboår.",
                "**Den generelle 407-yrkessaken (mart.arbeidsmarked_yrke_aar) mister hele "
                "2025 for akkurat dette yrket**, uten at noen sjekk der fanger det. Den "
                "modellen ankrer alle årspunkter til 2. kvartal, og bestanden for "
                "flygeledere mangler nøyaktig 2025K2 (og 2025K3) — et generelt hull i "
                "kilden som rammer 2 av 583 yrkeskoder det kvartalet, og flygeledere er en "
                "av dem. Uten en bestandsverdi å ankre til, faller hele 2025-raden bort der. "
                "Denne saken bygger derfor egne tabeller på hele kvartalsserien i stedet for "
                "å lese av den eksisterende.",
                "Begge lønnskildene er avtalt lønn omregnet til heltid, pluss uregelmessige "
                "tillegg og bonus — overtid er ikke med i noen av dem. De måler likevel ikke "
                "det samme: den årlige tabellen er ett punkt i november, alle sektorer; den "
                "kvartalsvise er kvartalets egen median. Et yrke som bytter mellom kildene "
                f"kan hoppe litt av en grunn som ikke er en lønnsendring — her er avviket "
                f"mellom dem {_pst(avvik_kilder)} i det ene overlappende punktet (2025K4 mot "
                "2025 årlig), som er nær nok til at de to i det minste ikke motsier "
                "hverandre.",
                "**Reallønn er deflatert med KPI totalindeks (SSB tabell 14700) til "
                f"{KPI_REFERANSE_MAANED[:4]}-kroner** — novemberindeksen det siste året den "
                "årlige kilden dekker. Den årlige serien deflateres med novemberindeksen "
                "samme år; den kvartalsvise med snittet av kvartalets tre måneder. Begge "
                "bruker samme referanse, så et bytte av kilde ikke også blir et bytte av "
                "prisbasis.",
                "**SSB melder om et brudd i lønnsnivået i 1. kvartal 2020**: bedre "
                "rapportering fra opplysningspliktige ga et høyere målt nivå generelt, ikke "
                "avgrenset til én næring. Det ligger midt i strekningen 2015-2020 som denne "
                "saken bruker til å vise den sterkeste veksten, og noe av den kan derfor "
                "være bedre registrering snarere enn en reell lønnsøkning.",
                "Lønnsoppgjørstallene fra Spekter/Avinor er hentet fra deres offentlige "
                "pressemateriell i forbindelse med meklingen, ikke fra SSB, og er snitt — "
                "ikke median. De to tallseriene i denne saken er derfor ikke direkte "
                "sammenlignbare uten forbeholdet i figurteksten over.",
                "**SSBs arbeidstidstabell for yrket (tabell 12542) er sjekket og forkastet.** "
                "Den bryter sysselsatte flygeledere ned på seks arbeidstidskategorier per år, "
                "men tabellen selv opplyser at «alle ett-tall og to-tall … er endret til '0' "
                "eller '3' for å ivareta personvernet» — for et yrke på 700-800 personer "
                "fordelt på seks kategorier er de fleste cellene små nok til å rammes. Bare "
                "hovedkategorien (35-37 timer, som over 80 % faller i) er stor nok til å "
                "være til å stole på, og selv den sier ingenting om vaktlengde, pauser eller "
                "overtid — det NFF faktisk beskriver. Tabellen er derfor ikke brukt her, "
                "verken i tekst eller figur.",
                "**EUROCONTROL/PRBs Annual Monitoring Report for Norge (2020-2024, én PDF "
                "per år) er ikke en datatabell, men løpende tekst.** Tallene under "
                "«Arbeidsbelastning» er hentet med regulære uttrykk mot nøyaktig de "
                "formuleringene rapportene faktisk bruker, kontrollert mot alle fem årene — "
                "se `statman/models/clean_eurocontrol_norge.py`. Rapportene nevner ikke alle "
                "tre kontrollsentralene (Bodø/Oslo/Stavanger ACC) med et konkret tall hvert "
                "år, og ATCO-bemanning har bare et grunntall for 2024 — tidligere år oppgir "
                "kun avvik fra planen, ikke et tall å trekke fra. Ingen av hullene er fylt.",
                f"Modellene `{MODEL_LONN}`, `{MODEL_BESTAND}`, `{MODEL_BODO}` og "
                f"`{MODEL_BEMANNING}`, bygget av statman "
                f"{bygg['built_at'][:19].replace('T', ' ')}Z "
                f"(EUROCONTROL-modellene {bygg_eurocontrol['built_at'][:19].replace('T', ' ')}Z).",
            )),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker="Flygeledere · SSB tabell 11418/11658 · EUROCONTROL/PRB",
        title="Lønna til flygelederne — og fire år ingen har målt den",
        lead=(
            "Flygelederne streiker. Uansett hva striden egentlig står om — partene er "
            "uenige, se «Lønnsoppgjøret» under — er dette hva SSB har publisert om lønna "
            "til yrket streiken gjelder: en tydelig realvekst i første halvdel av tiåret, et "
            "fall i andre, og et firårig hull midt i der ingenting er målt i det hele tatt. "
            "«Arbeidsbelastning» under ser på det NFF selv sier streiken faktisk handler om."
        ),
        published=PUBLISERT,
        sections=(lonn_seksjon, reallonn_seksjon, oppgjor_seksjon, arbeidsbelastning_seksjon, metode),
        caveats=METRICS,
        provenance={
            "Kilde": f"SSB tabell {TABELL_KVARTAL} og {TABELL_LONN_AAR}, yrke {YRKE}",
            "Hentet": bygg["built_at"][:19] + "Z",
            "Yrkesstandard": f"STYRK-08 via SSB KLASS 7, per {STYRK_DATO}",
            "Lønnsoppgjørstall": f"Spekter/Avinor, snitt per {SPEKTER_DATO} (ikke SSB)",
            "Arbeidsbelastning": "EUROCONTROL/PRB Annual Monitoring Report, Norge, 2020-2024",
            "Modeller": f"{MODEL_LONN} · {MODEL_BESTAND} · {MODEL_BODO} · {MODEL_BEMANNING}",
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "alle rader i mart.flygeledere_lonn"),
            ("arbeidsbelastning.csv", "alle rader i mart.eurocontrol_bodo_arbeidsbelastning"),
            ("lonn.png", "median månedslønn, nominelt, 2015-2026"),
            ("reallonn.png", "median månedslønn, faste kroner, 2015-2026"),
            ("oppgjor.png", "de tre siste kvartalene mot lønnsoppgjøret"),
            ("bodo_produktivitet.png", "IFR-bevegelser per sektor-åpningstime, Bodø ACC, 2020-2024"),
        ),
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    lonn = io.load(MODEL_LONN)
    bestand = io.load(MODEL_BESTAND).row(0, named=True)
    bodo = io.load(MODEL_BODO)
    bemanning = io.load(MODEL_BEMANNING)
    bygg = io.read_manifest(MODEL_LONN)
    bygg_eurocontrol = io.read_manifest(MODEL_BODO)

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    lonn.sort(["kilde", "periode"]).write_csv(csv_path)
    eurocontrol_csv_path = target / "arbeidsbelastning.csv"
    bodo.sort("aar").write_csv(eurocontrol_csv_path)

    figurer = [
        _plot_lonn(lonn, "median_lonn_nominell", "Median månedslønn, nominelt",
                   "Kroner per måned", target / "lonn.png"),
        _plot_lonn(lonn, "median_lonn_realt", f"Median månedslønn, {KPI_REFERANSE_MAANED[:4]}-kroner",
                   "Kroner per måned", target / "reallonn.png"),
        _plot_oppgjor(lonn.filter(pl.col("kilde") == "kvartalsvis"), target / "oppgjor.png"),
        _plot_bodo_produktivitet(bodo, target / "bodo_produktivitet.png"),
    ]

    art = artikkel(lonn, bestand, bodo, bemanning, bygg, bygg_eurocontrol)
    art.validate(target)
    return [
        csv_path,
        eurocontrol_csv_path,
        *figurer,
        publish.markdown.write(art, target / "notat.md"),
        art.write(target),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
