"""Ende-til-ende-eksempel: befolkningsvekst i alle norske kommuner 2011–2025.

Ekte tall fra SSB, hele veien fra API-kall til sakspakke. Kjeden er:

    ssb.fetch_table(06913)  ->  raw/ssb/06913_kommune
                                raw/ssb/06913_fylke
      -> clean.befolkning_kommune, clean.befolkning_fylke
      -> mart.befolkning_kommune_aar, mart.befolkning_fylke_aar
      -> mart.befolkningsvekst
      -> output/befolkningsvekst_kommune/     (sakspakke)
      -> statman publish befolkningsvekst_kommune  -> docs/   (artikkel)

Det egentlige arbeidet i denne saken er ikke å regne ut prosentvekst. Det er
å vite hvilke kommuner man *ikke* kan regne prosentvekst for. Femten år
dekker to kommunereformer, én fylkesreform, én kommunedeling og et titalls
grensejusteringer. Se ``statman/models/mart_befolkning.py``.

Kjør:  uv run statman example befolkning
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Final

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, jsonstat, publish  # noqa: E402
from statman.models.clean_ssb_befolkning import RAW_FYLKE, RAW_KOMMUNE, VARIABLER  # noqa: E402
from statman.models.mart_befolkning import PERIODE_AAR, TOLERANSE  # noqa: E402
from statman.sources import ssb  # noqa: E402

TABELL: Final[str] = "06913"
SLUG: Final[str] = "befolkningsvekst_kommune"

# Publiseringsdatoen er en redaksjonell opplysning, ikke et tidsstempel. Den
# ble satt da saken først ble publisert, og skal ikke flytte seg fordi
# modellene bygges på nytt: da ville en ren figurendring sendt saken til
# toppen av arkivet som om tallene var nye. Når tallene *er* nye, settes den
# for hånd — det er nettopp da noen bør ta stilling til det.
PUBLISERT: Final[str] = "2026-08-02"
MODEL_VEKST: Final[str] = "mart.befolkningsvekst"
MODEL_AAR: Final[str] = "mart.befolkning_kommune_aar"
MODEL_FYLKE: Final[str] = "mart.befolkning_fylke_aar"

# Folkemengden måles 1. januar, så N års vekst krever N+1 målinger.
AARGANGER: Final[int] = PERIODE_AAR + 1

# Byggemål. mart.befolkning_kommune_aar er oppstrøms og kommer med;
# fylkestabellen er en egen gren og må navngis.
MODELS: Final[list[str]] = [MODEL_VEKST, MODEL_FYLKE]

METRICS: Final[tuple[str, ...]] = (
    "folkevekst_pst",
    "fodselsoverskudd_sum",
    "nettoinnflytting_sum",
    "folkemengde",
)

# Hvor mange kommuner som vises i topp- og bunnlista.
N_TOPP: Final[int] = 20

# Hvor mange kommuner som navngis i hver ende av ekstremgrafen. Fem i hver
# retning er det som får plass i en tegnforklaring man faktisk leser.
N_EKSTREM: Final[int] = 5

# Utsnitt for årsgrafen. Valgt så bare en håndfull kommuneår faller utenfor —
# uten det ville Etnedals +27 prosent i 2025 klemt alt annet flatt. Antallet
# som havner utenfor telles opp og skrives i kildelinja.
Y_MIN: Final[float] = -0.05
Y_MAKS: Final[float] = 0.08

# Fargene i PNG-ene skal være de samme som i figurene sida tegner, ellers
# ser leseren to versjoner av samme graf. Verdiene speiler fargerollene i
# statman/publish/assets/graf.css, der begrunnelsen og målingene står.
FARGE_VEKST: Final[str] = "#2a9d5c"
FARGE_FALL: Final[str] = "#a33b32"
FARGE_FLYTTING: Final[str] = "#2b6ca3"
FARGE_FODSEL: Final[str] = "#c07a2b"


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent tabell 06913 i to utsnitt: kommuner og fylker.

    Begge bruker en aggregert kodeliste. ``agg_KommSummerHist`` er «Kommuner
    2024, sammenslåtte tidsserier» — SSB summerer historikken til kommuner
    som er slått sammen, opp til dagens grenser. Uten den ville halve
    Norge hatt seriebrudd i 2020.
    """
    ssb.probe()
    contents = ",".join(VARIABLER)
    datasets = {
        RAW_KOMMUNE: "agg_KommSummerHist",
        RAW_FYLKE: "agg_KommFylkerHist",
    }
    written: dict[str, Path] = {}
    for ref, codelist in datasets.items():
        _, _, dataset = ref.partition("/")
        written[ref] = ssb.fetch_table(
            TABELL,
            value_codes={"Region": "*", "ContentsCode": contents, "Tid": f"TOP({AARGANGER})"},
            codelists={"Region": codelist},
            dataset=dataset,
        )
    return written


# --------------------------------------------------------------------------
# Presentasjon
# --------------------------------------------------------------------------
def kort_navn(navn: str) -> str:
    """``"Troms - Romsa - Tromssa"`` -> ``"Troms"``.

    Bare for akse- og punktetiketter, der det ikke er plass. Det fulle
    flerspråklige navnet står i dataene og i CSV-en.
    """
    return navn.split(" - ")[0]


def _etikett(rad: dict) -> str:
    """«Frøya» -> «Frøya (Trøndelag)», men «Våler (Østfold)» står som det er.

    SSB skiller kommuner med samme navn ved å sette fylket i parentes selv.
    Da skal vi ikke sette det på en gang til.
    """
    navn = rad["kommune"]
    return navn if navn.endswith(")") else f"{navn} ({kort_navn(rad['fylke'])})"


def _pst(verdi: float) -> str:
    return f"{verdi * 100:+.1f} %".replace(".", ",")


def _antall(verdi: float) -> str:
    return f"{int(round(verdi)):,}".replace(",", " ")


def _fortegn(verdi: float) -> str:
    return f"{int(round(verdi)):+,}".replace(",", " ")


def _akse_pst(verdi: float, _pos: object = None) -> str:
    """Aksemerke i prosent, med desimal bare når merkene trenger den.

    Uten dette blir en akse med halvprosent-merker stående med «1, 1, 0, 0»,
    fordi to nabomerker rundes til samme heltall.
    """
    if abs(verdi) < 1e-12:
        return "0 %"
    tall = f"{verdi * 100:.1f}".rstrip("0").rstrip(".")
    return f"{tall} %".replace(".", ",")


# --------------------------------------------------------------------------
# Grafer
# --------------------------------------------------------------------------
def _plot_topp_bunn(vekst: pl.DataFrame, path: Path, periode: str, aar_slutt: int) -> Path:
    """Topp og bunn på prosentvekst. Bare sammenlignbare kommuner."""
    topp = vekst.sort("vekst_pst", descending=True).head(N_TOPP)
    bunn = vekst.sort("vekst_pst").head(N_TOPP).sort("vekst_pst", descending=True)

    fig, axes = plt.subplots(1, 2, figsize=(13, 8))
    for ax, del_df, tittel in (
        (axes[0], topp, f"Størst vekst — topp {N_TOPP}"),
        (axes[1], bunn, f"Størst nedgang — bunn {N_TOPP}"),
    ):
        etiketter = [_etikett(rad) for rad in del_df.iter_rows(named=True)]
        verdier = del_df["vekst_pst"].to_list()
        posisjoner = range(len(verdier))
        farger = [FARGE_VEKST if v >= 0 else FARGE_FALL for v in verdier]
        ax.barh(list(posisjoner), verdier, color=farger, height=0.72)
        ax.set_yticks(list(posisjoner), etiketter, fontsize=9)
        ax.invert_yaxis()
        ax.set_title(tittel, loc="left", fontsize=11)
        ax.axvline(0, color="0.3", linewidth=0.8)
        ax.grid(True, axis="x", alpha=0.25, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_formatter(_akse_pst)

        # Folkemengden hører hjemme rett ved siden av prosenten. 27 prosent i
        # en kommune med 1 257 innbyggere er noe annet enn 27 prosent i Oslo.
        spenn = max(abs(min(verdier)), abs(max(verdier))) or 1.0
        for i, rad in enumerate(del_df.iter_rows(named=True)):
            v = rad["vekst_pst"]
            ax.text(
                v + (0.02 * spenn if v >= 0 else -0.02 * spenn),
                i,
                _antall(rad["folkemengde_slutt"]),
                va="center",
                ha="left" if v >= 0 else "right",
                fontsize=8,
                color="0.35",
            )
        ax.set_xlim(min(0, min(verdier)) * 1.35, max(0, max(verdier)) * 1.35)

    fig.suptitle(
        f"Befolkningsvekst i norske kommuner, {periode}",
        x=0.01,
        ha="left",
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.005,
        f"Kilde: SSB tabell 06913. Tall ved siden av søylene er innbyggere 1.1.{aar_slutt}. "
        f"Kommuner med grenseendring over {_pst(TOLERANSE).lstrip(chr(43))} av folketallet, "
        "eller uten historikk i dagens inndeling, er holdt utenfor.",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _plot_aarlig(aar_df: pl.DataFrame, path: Path, periode: str) -> Path:
    """Årlig rate for hver kommune, i tre paneler med felles y-akse.

    Felles akse er hele poenget. Fødselsoverskuddet holder seg innenfor et
    par prosent i alle kommuner alle år, mens flyttingen spriker fra minus
    åtte til pluss tjuesju. Med hver sin akse ville panelene sett like ut.
    """
    paneler = (
        ("vekst_pst", "folketilvekst", "Samlet folketilvekst", FARGE_VEKST),
        ("nettoinnflytting_pst", "nettoinnflytting", "Nettoinnflytting", FARGE_FLYTTING),
        ("fodselsoverskudd_pst", "fodselsoverskudd", "Fødselsoverskudd", FARGE_FODSEL),
    )
    df = aar_df.filter(pl.col("folketilvekst").is_not_null())
    aar = sorted(df["aar"].unique().to_list())
    kolonnenavn = [str(a) for a in aar]

    # Kommuneår som faller utenfor utsnittet i minst ett av panelene. Telles
    # én gang hver, ikke én gang per panel.
    utenfor = df.filter(
        pl.any_horizontal(
            [(pl.col(rate) < Y_MIN) | (pl.col(rate) > Y_MAKS) for rate, *_ in paneler]
        )
    ).height

    fig, axes = plt.subplots(1, 3, figsize=(14, 6.5), sharey=True, sharex=True)

    for ax, (rate, antall, tittel, farge) in zip(axes, paneler):
        # Én tynn linje per kommune. Enkeltlinjene er ikke til å lese av —
        # de er der for å vise spredningen bak medianen.
        bred = df.pivot(on="aar", index="kommunenummer", values=rate).sort("kommunenummer")
        for rad in bred.select(kolonnenavn).iter_rows():
            verdier = [float("nan") if v is None else v for v in rad]
            ax.plot(aar, verdier, color="0.4", alpha=0.09, linewidth=0.7)

        oppsummert = (
            df.group_by("aar")
            .agg(
                pl.col(rate).quantile(0.10).alias("p10"),
                pl.col(rate).quantile(0.90).alias("p90"),
                pl.col(rate).median().alias("median"),
                (pl.col(antall).sum() / pl.col("folkemengde").sum()).alias("landet"),
            )
            .sort("aar")
        )
        ax.fill_between(
            aar,
            oppsummert["p10"].to_list(),
            oppsummert["p90"].to_list(),
            color=farge,
            alpha=0.18,
            linewidth=0,
            label="10.–90. persentil",
        )
        ax.plot(aar, oppsummert["median"].to_list(), color=farge, linewidth=2.4, label="Median kommune")
        ax.plot(
            aar,
            oppsummert["landet"].to_list(),
            color="0.15",
            linewidth=1.6,
            linestyle="--",
            label="Hele landet",
        )

        ax.axhline(0, color="0.35", linewidth=0.9)
        ax.set_title(tittel, loc="left", fontsize=12, fontweight="bold", color=farge)
        # Femten årstall får ikke plass ved siden av hverandre. Vi merker
        # hvert n-te, men lar alltid første og siste år stå.
        steg = max(1, round(len(aar) / 6))
        merket = [a for i, a in enumerate(aar) if i % steg == 0 or a == aar[-1]]
        ax.set_xticks(merket, [str(a) for a in merket], fontsize=9)
        ax.grid(True, axis="y", alpha=0.25, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.set_major_formatter(_akse_pst)

    axes[0].set_ylim(Y_MIN, Y_MAKS)
    axes[0].set_ylabel("Endring i året, prosent av folketallet 1. januar")
    axes[0].legend(frameon=False, fontsize=9, loc="upper left")

    fig.suptitle(
        f"Årlig befolkningsendring i hver av {df['kommunenummer'].n_unique()} kommuner, {periode}",
        x=0.01,
        ha="left",
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.005,
        "Kilde: SSB tabell 06913. Én grå linje per kommune. Felles y-akse i alle tre paneler. "
        f"{utenfor} kommuneår faller utenfor utsnittet i minst ett panel. «Hele landet» er "
        "summen av endringene delt på samlet folketall, ikke medianen av kommunene.",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _ekstremer(
    vekst: pl.DataFrame, sum_kolonne: str, antall: int = N_EKSTREM
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """De ``antall`` høyeste og laveste på *andel* — ikke på antall personer.

    Rangeringen går på komponentsummen delt på folketallet ved starten av
    perioden. Uten nevneren ville lista blitt de største kommunene i landet,
    som er en helt annen sak enn de som endret seg mest.
    """
    rangert = vekst.with_columns(
        (pl.col(sum_kolonne) / pl.col("folkemengde_start")).alias("_kumulativ")
    ).sort("_kumulativ", descending=True)
    return rangert.head(antall), rangert.tail(antall).reverse()


def _plot_ekstremer(
    aar_df: pl.DataFrame, vekst: pl.DataFrame, path: Path, periode: str
) -> Path:
    """Samme tre komponenter som årsgrafen, men bare ytterpunktene — navngitt.

    Spaghettigrafen viser fordelingen og skjuler kommunene. Denne gjør det
    motsatte. Utvalget er de fem høyeste og fem laveste på *kumulativ* rate
    over hele perioden, ikke på enkeltår; ellers ville lista blitt fylt av
    kommuner som hadde ett rart år.

    Merk at hvert panel her har sin egen y-akse. Årsgrafen deler akse med
    vilje, for å vise at fødselsoverskuddet varierer lite. Her er poenget å
    kunne lese av enkeltkommuner, og da må hvert panel få bruke plassen.
    """
    paneler = (
        ("vekst_pst", "folketilvekst_sum", "Samlet folketilvekst", FARGE_VEKST),
        ("nettoinnflytting_pst", "nettoinnflytting_sum", "Nettoinnflytting", FARGE_FLYTTING),
        ("fodselsoverskudd_pst", "fodselsoverskudd_sum", "Fødselsoverskudd", FARGE_FODSEL),
    )
    df = aar_df.filter(pl.col("folketilvekst").is_not_null())
    aar = sorted(df["aar"].unique().to_list())
    sml = vekst.filter(pl.col("sammenlignbar"))

    fig, axes = plt.subplots(3, 1, figsize=(13, 13.5), sharex=True)

    for ax, (rate, sum_kolonne, tittel, farge) in zip(axes, paneler):
        topp, bunn = _ekstremer(sml, sum_kolonne)
        grupper = (
            ("Størst økning", topp, plt.get_cmap("summer")),
            ("Størst nedgang", bunn, plt.get_cmap("autumn")),
        )

        # Medianen av alle sammenlignbare kommuner, som målestokk å lese mot.
        median = (
            df.filter(pl.col("kommunenummer").is_in(sml["kommunenummer"].to_list()))
            .group_by("aar")
            .agg(pl.col(rate).median().alias("median"))
            .sort("aar")
        )
        ax.plot(
            aar,
            median["median"].to_list(),
            color="0.35",
            linewidth=2.0,
            linestyle=(0, (4, 2)),
            label="Median kommune",
            zorder=2,
        )

        plasserte = []
        for tekst, gruppe, kart in grupper:
            handles = []
            for i, rad in enumerate(gruppe.iter_rows(named=True)):
                serie = (
                    df.filter(pl.col("kommunenummer") == rad["kommunenummer"])
                    .sort("aar")
                    .select("aar", rate)
                )
                verdier = dict(zip(serie["aar"].to_list(), serie[rate].to_list()))
                (linje,) = ax.plot(
                    aar,
                    [verdier.get(a, float("nan")) for a in aar],
                    color=kart(i / max(1, N_EKSTREM - 1) * 0.7),
                    linewidth=1.8,
                    marker="o",
                    markersize=3.2,
                    label=(
                        f"{kort_navn(rad['kommune'])}  {_pst(rad['_kumulativ'])}"
                        f"  ({_antall(rad['folkemengde_start'])} innb.)"
                    ),
                    zorder=3,
                )
                handles.append(linje)
            plasserte.append((tekst, handles))

        ax.axhline(0, color="0.35", linewidth=0.9)
        ax.set_title(tittel, loc="left", fontsize=12.5, fontweight="bold", color=farge)
        ax.grid(True, axis="y", alpha=0.25, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.set_major_formatter(_akse_pst)
        ax.set_ylabel("Endring i året")

        # To tegnforklaringer utenfor aksen, så navnene ikke legger seg
        # oppå linjene de skal forklare.
        forste = ax.legend(
            handles=plasserte[0][1],
            title=f"{plasserte[0][0]} {periode}",
            loc="upper left",
            bbox_to_anchor=(1.01, 1.02),
            frameon=False,
            fontsize=8.5,
            title_fontsize=9,
            alignment="left",
        )
        ax.add_artist(forste)
        ax.legend(
            handles=plasserte[1][1],
            title=plasserte[1][0],
            loc="lower left",
            bbox_to_anchor=(1.01, -0.02),
            frameon=False,
            fontsize=8.5,
            title_fontsize=9,
            alignment="left",
        )

    steg = max(1, round(len(aar) / 8))
    merket = [a for i, a in enumerate(aar) if i % steg == 0 or a == aar[-1]]
    axes[-1].set_xticks(merket, [str(a) for a in merket], fontsize=9)

    fig.suptitle(
        f"Kommunene med størst og minst endring, {periode}",
        x=0.01,
        ha="left",
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.004,
        "Kilde: SSB tabell 06913. Utvalget er de fem høyeste og laveste på samlet endring "
        f"i prosent over hele perioden, målt mot folketallet 1.1.{aar[0]} — ikke på antall "
        "personer.\nProsenten i tegnforklaringen er den samlede endringen; kurvene viser "
        "år for år. Hvert panel har sin egen y-akse. Bare sammenlignbare kommuner.",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _merkekandidater(df: pl.DataFrame, bredde: float, hoyde: float) -> list[dict]:
    """Et fåtall navn: ytterpunktene på hver akse, pluss de største kommunene.

    Kandidater som havner oppå et navn vi allerede har satt, hoppes over —
    billigere enn en ordentlig kollisjonsløser, og godt nok når vi bare
    skal ha rundt ti navn.
    """
    kandidater: list[dict] = []
    for kolonne in ("flytting", "fodsel"):
        for synkende in (True, False):
            kandidater += df.sort(kolonne, descending=synkende).head(2).to_dicts()
    kandidater += df.sort("folkemengde_start", descending=True).head(3).to_dicts()

    valgt: list[dict] = []
    for rad in kandidater:
        for satt in valgt:
            if (
                abs(rad["fodsel"] - satt["fodsel"]) < 0.06 * bredde
                and abs(rad["flytting"] - satt["flytting"]) < 0.045 * hoyde
            ):
                break
        else:
            valgt.append(rad)
    return valgt


def _plot_komponenter(vekst: pl.DataFrame, path: Path, periode: str) -> Path:
    """Fødselsoverskudd mot nettoinnflytting. Diagonalen er nullvekst."""
    df = vekst.with_columns(
        (pl.col("fodselsoverskudd_sum") / pl.col("folkemengde_start") * 1000).alias("fodsel"),
        (pl.col("nettoinnflytting_sum") / pl.col("folkemengde_start") * 1000).alias("flytting"),
    )
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.scatter(
        df["fodsel"].to_list(),
        df["flytting"].to_list(),
        s=[max(9.0, (n / 1500) ** 0.85) for n in df["folkemengde_start"].to_list()],
        c=[FARGE_VEKST if v >= 0 else FARGE_FALL for v in df["vekst_pst"].to_list()],
        alpha=0.55,
        linewidths=0,
    )

    # Aksene får hvert sitt spenn. Å tvinge dem like ville gjort figuren
    # kvadratisk rundt det ene ekstrempunktet og klemt resten sammen.
    def _spenn(serie: pl.Series) -> tuple[float, float]:
        lav, hoy = float(serie.min()), float(serie.max())
        pute = (hoy - lav) * 0.07
        return lav - pute, hoy + pute

    x_lav, x_hoy = _spenn(df["fodsel"])
    y_lav, y_hoy = _spenn(df["flytting"])

    # Nullvekstlinjen: fødselsoverskudd + nettoinnflytting = 0.
    ax.plot([x_lav, x_hoy], [-x_lav, -x_hoy], color="0.35", linewidth=1.0, linestyle="--")
    ax.axhline(0, color="0.8", linewidth=0.8)
    ax.axvline(0, color="0.8", linewidth=0.8)
    ax.set_xlim(x_lav, x_hoy)
    ax.set_ylim(y_lav, y_hoy)
    ax.text(
        x_hoy - (x_hoy - x_lav) * 0.02,
        -x_hoy + (y_hoy - y_lav) * 0.02,
        "nullvekst",
        ha="right",
        va="bottom",
        fontsize=9,
        color="0.4",
        rotation=-12,
    )

    for rad in _merkekandidater(df, x_hoy - x_lav, y_hoy - y_lav):
        ax.annotate(
            kort_navn(rad["kommune"]),
            (rad["fodsel"], rad["flytting"]),
            textcoords="offset points",
            xytext=(7, 4),
            fontsize=8.5,
            color="0.2",
        )

    ax.set_xlabel("Fødselsoverskudd per 1 000 innbyggere, sum 2021–2025")
    ax.set_ylabel("Nettoinnflytting per 1 000 innbyggere, sum 2021–2025")
    ax.grid(True, alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(
        "Nesten all kommunal befolkningsvekst er flytting, ikke fødsler",
        loc="left",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_title(f"{periode}. Flatestørrelse følger folketallet.", loc="right", fontsize=9, color="0.35")
    fig.text(
        0.01,
        0.005,
        f"Kilde: SSB tabell 06913. Grønt = vekst, rødt = nedgang. Kommuner med grenseendring "
        f"over {_pst(TOLERANSE).lstrip(chr(43))} av folketallet er holdt utenfor.",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _plot_fylke(fylke: pl.DataFrame, path: Path, periode: str, aar_start: int) -> Path:
    """Fylkesvis vekst, delt i de to komponentene."""
    df = fylke.sort("vekst_pst")
    etiketter = [kort_navn(n) for n in df["fylke"].to_list()]
    posisjoner = list(range(df.height))
    fodsel = (df["fodselsoverskudd_sum"] / df["folkemengde_start"] * 100).to_list()
    flytting = (df["nettoinnflytting_sum"] / df["folkemengde_start"] * 100).to_list()

    fig, ax = plt.subplots(figsize=(11, 7))
    ax.barh(posisjoner, flytting, color=FARGE_FLYTTING, height=0.62, label="Nettoinnflytting")
    # Fødselsoverskuddet stables fra der flyttingen slutter når de har samme
    # fortegn, ellers ville et negativt bidrag skjult et positivt.
    bunn = [f if (f < 0) == (b < 0) else 0.0 for f, b in zip(flytting, fodsel)]
    ax.barh(posisjoner, fodsel, left=bunn, color=FARGE_FODSEL, height=0.62, label="Fødselsoverskudd")

    for i, total in enumerate(df["vekst_pst"].to_list()):
        ax.plot([total * 100], [i], marker="D", color="0.15", markersize=5, zorder=5)

    ax.set_yticks(posisjoner, etiketter, fontsize=10)
    ax.axvline(0, color="0.3", linewidth=0.8)
    ax.grid(True, axis="x", alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_formatter(lambda v, _: _akse_pst(v / 100))
    ax.set_xlabel(f"Bidrag til befolkningsvekst, prosent av folketallet 1.1.{aar_start}")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title(
        f"Fylkesvis befolkningsvekst {periode}, delt i fødselsoverskudd og flytting",
        loc="left",
        fontsize=13,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.005,
        "Kilde: SSB tabell 06913. Sorte punkter er samlet vekst; avviket fra søylene er "
        "restleddet SSB ikke fordeler.\nHentet fra SSBs fylkesserie, som også har med "
        "personene i kommuner som ble delt i 2020.",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# Figurer som tegnes i sida
# --------------------------------------------------------------------------
# PNG-ene over er fortsatt fasit: de står i notatet, og de står i sida for en
# leser uten JavaScript. Det som følger er de samme tallene satt opp slik at
# sida kan tegne dem selv — og dermed la leseren finne sin egen kommune.
#
# Merk hva som *ikke* sendes: ingen farger og ingen piksler. Analysen sier at
# et merke er «vekst», publiseringslaget bestemmer hvilken grønn det blir.
LENKE: Final[str] = "kommune"


def _akse(lav: float, hoy: float, steg: float, etikett: str, tekst) -> publish.Axis:
    """Et utsnitt med luft, og aksemerker på runde tall inni det.

    Utsnittet er et valg — hvor mye av halen som får være med — og tas her.
    Rendereren skalerer bare verdi til piksel innenfor det den får oppgitt.
    """
    pute = (hoy - lav) * 0.05
    lo, hi = lav - pute, hoy + pute
    merker: list[float] = []
    v = math.ceil(lo / steg) * steg
    while v <= hi + 1e-9:
        merker.append(round(v, 6))
        v += steg
    return publish.Axis(
        label=etikett,
        lo=lo,
        hi=hi,
        ticks=tuple(merker),
        tick_labels=tuple(tekst(m) for m in merker),
    )


def _tone(vekst: float) -> str:
    """Fortegnet avgjøres på den fulle verdien, aldri på den avrundede.

    Masfjorden vokste med nøyaktig 0 personer, og to kommuner ligger på
    ±0,04 prosent. Spør man «er prosenten større enn null» etter avrunding,
    havner alle tre på feil side.
    """
    if vekst > 0:
        return "vekst"
    if vekst < 0:
        return "fall"
    return "noytral"


def _avlesning(rad: dict) -> tuple[publish.Readout, ...]:
    """Det boblen viser. Ferdig formatert her, aldri i nettleseren."""
    return (
        publish.Readout("Vekst", _pst(rad["vekst_pst"]), _tone(rad["vekst"])),
        publish.Readout("Nettoinnflytting", _fortegn(rad["nettoinnflytting_sum"]), "kat1"),
        publish.Readout("Fødselsoverskudd", _fortegn(rad["fodselsoverskudd_sum"]), "kat2"),
        publish.Readout("Folketall", _antall(rad["folkemengde_slutt"])),
    )


def _graf_komponenter(sml: pl.DataFrame, kilde: str) -> publish.Chart:
    """Punktskyen, tegnet i sida. Samme tall som ``komponenter.png``."""
    df = sml.with_columns(
        (pl.col("fodselsoverskudd_sum") / pl.col("folkemengde_start") * 1000).alias("fodsel"),
        (pl.col("nettoinnflytting_sum") / pl.col("folkemengde_start") * 1000).alias("flytting"),
    )
    x_lav, x_hoy = float(df["fodsel"].min()), float(df["fodsel"].max())
    y_lav, y_hoy = float(df["flytting"].min()), float(df["flytting"].max())
    storst = float(df["folkemengde_slutt"].max())

    # De samme navnene som PNG-en setter, så de to figurene peker på det samme.
    navngitt = {
        rad["kommune"] for rad in _merkekandidater(df, x_hoy - x_lav, y_hoy - y_lav)
    }

    merker = tuple(
        publish.Mark(
            label=kort_navn(rad["kommune"]),
            group=kort_navn(rad["fylke"]),
            x=round(rad["fodsel"], 1),
            y=round(rad["flytting"], 1),
            # Flaten følger folketallet, så radien følger kvadratrota. Tallet
            # er relativt (0–1); hvor mange piksler det blir er sidas sak.
            size=round(math.sqrt(rad["folkemengde_slutt"] / storst), 3),
            tone=_tone(rad["vekst"]),
            values=_avlesning(rad),
            note=_pst(rad["vekst_pst"]),
            pin=rad["kommune"] in navngitt,
        )
        for rad in df.iter_rows(named=True)
    )

    return publish.Chart(
        kind="scatter",
        marks=merker,
        fallback="komponenter.png",
        alt="Punktdiagram: fødselsoverskudd langs x-aksen, nettoinnflytting "
        "langs y-aksen, én prikk per kommune.",
        x=_akse(x_lav, x_hoy, 50, "Fødselsoverskudd per 1 000 innbyggere →", _antall),
        y=_akse(y_lav, y_hoy, 100, "← Nettoinnflytting per 1 000 innbyggere", _antall),
        legend=(("vekst", "Kommunen vokste"), ("fall", "Kommunen falt")),
        guides=(publish.Guide("diagonal", 0.0, ("nullvekst",)),),
        link=LENKE,
        picker="Framhev kommune",
        group_label="Avgrens til fylke",
        caption="Flaten følger folketallet. Den stiplede diagonalen er nullvekst. "
        "At skyen ligger langt mer spredt loddrett enn vannrett, er det samme "
        "funnet som i punktet over — sett fra siden. Pekeren treffer nærmeste "
        "kommune; du trenger ikke treffe prikken.",
        source=kilde,
    )


def _graf_rangstripe(sml: pl.DataFrame, kilde: str) -> publish.Chart:
    """Alle kommunene på én linje, rangert. Svarer på «hvor står min?».

    Den bærer ``vekst_topp_bunn.png`` som fallback og erstatter den: figuren
    viser den samme rangeringen, bare hele veien ned i stedet for tjue i hver
    ende. Uten skript er det topp- og bunnlista leseren får, som før.
    """
    df = sml.sort("vekst_pst", descending=True)
    antall = df.height
    vokste = df.filter(pl.col("vekst") > 0).height
    falt = df.filter(pl.col("vekst") < 0).height

    # Vokste + falt er ikke nødvendigvis lik antallet: en kommune kan ende på
    # nøyaktig samme folketall. Det er ett tall å forklare, ikke et avvik å
    # skjule — så vi finner det og skriver det i bildeteksten.
    flate = df.filter(pl.col("vekst") == 0)
    forklaring = ""
    if flate.height == 1:
        forklaring = (
            f" De to tallene over summerer seg til {vokste + falt} og ikke {antall}: "
            f"{kort_navn(flate.row(0, named=True)['kommune'])} endte på nøyaktig samme "
            "folketall som den startet på, og hører ikke hjemme i noen av gruppene."
        )
    elif flate.height > 1:
        forklaring = (
            f" De to tallene over summerer seg til {vokste + falt} og ikke {antall}: "
            f"{flate.height} kommuner endte på nøyaktig samme folketall som de "
            "startet på."
        )

    merker = tuple(
        publish.Mark(
            label=kort_navn(rad["kommune"]),
            group=kort_navn(rad["fylke"]),
            tone=_tone(rad["vekst"]),
            values=(
                publish.Readout("Vekst", _pst(rad["vekst_pst"]), _tone(rad["vekst"])),
                publish.Readout("Folketall", _antall(rad["folkemengde_slutt"])),
            ),
            note=f"nr. {i + 1} av {antall}",
        )
        for i, rad in enumerate(df.iter_rows(named=True))
    )

    topp = df.row(0, named=True)
    bunn = df.row(-1, named=True)
    return publish.Chart(
        kind="strip",
        marks=merker,
        fallback="vekst_topp_bunn.png",
        alt=f"To liggende søylediagram: de {N_TOPP} kommunene med størst vekst "
        f"og de {N_TOPP} med størst nedgang, i prosent.",
        # Aksen er rangeringen selv: merkene står i hver ende av lista, og
        # merketeksten er kommunen som ligger der.
        x=publish.Axis(
            lo=0,
            hi=antall - 1,
            ticks=(0, antall - 1),
            tick_labels=(
                f"{kort_navn(topp['kommune'])} {_pst(topp['vekst_pst'])}",
                f"{kort_navn(bunn['kommune'])} {_pst(bunn['vekst_pst'])}",
            ),
        ),
        guides=(
            publish.Guide("x", vokste - 0.5, (f"{vokste} vokste", f"{falt} falt")),
        ),
        link=LENKE,
        caption=f"Alle {antall} sammenlignbare kommunene på én linje, rangert — "
        "prosentvekst setter små kommuner både til topps og til bunns. Den valgte "
        "kommunen får en nål her også, så du ser med én gang om den er et ytterpunkt "
        "eller midt i flokken." + forklaring,
        source=kilde,
    )


def _graf_fylke(fylke: pl.DataFrame, aar_start: int) -> publish.Chart:
    """Fylkessøylene. Tallene kommer fra fylkesserien, ikke fra kommunesummen.

    Se :func:`_fylkesperiode` for hvorfor det er den eneste riktige kilden —
    en summering over kommunene mangler dem som ble delt i 2020.
    """
    df = fylke.sort("vekst_pst", descending=True)
    rader = list(df.iter_rows(named=True))

    def pst(rad: dict, kolonne: str) -> float:
        return rad[kolonne] / rad["folkemengde_start"] * 100

    # Utsnittet må romme både den negative og den positive enden av stabelen.
    lav = min(0.0, min(min(pst(r, "fodselsoverskudd_sum"), 0.0) for r in rader))
    hoy = max(
        max(pst(r, "nettoinnflytting_sum"), 0.0)
        + max(pst(r, "fodselsoverskudd_sum"), 0.0)
        for r in rader
    )

    merker = tuple(
        publish.Mark(
            label=kort_navn(rad["fylke"]),
            segments=(
                ("kat1", round(pst(rad, "nettoinnflytting_sum"), 2)),
                ("kat2", round(pst(rad, "fodselsoverskudd_sum"), 2)),
            ),
            note=_pst(rad["vekst_pst"]),
            values=(
                publish.Readout("Samlet vekst", _pst(rad["vekst_pst"]), _tone(rad["vekst"])),
                publish.Readout(
                    "Nettoinnflytting", _antall(rad["nettoinnflytting_sum"]), "kat1"
                ),
                publish.Readout(
                    "Fødselsoverskudd", _antall(rad["fodselsoverskudd_sum"]), "kat2"
                ),
                publish.Readout("Kommuner", str(rad["kommuner"])),
            ),
        )
        for rad in rader
    )

    return publish.Chart(
        kind="bars",
        marks=merker,
        fallback="fylke.png",
        alt="Liggende søyler per fylke, delt i nettoinnflytting og fødselsoverskudd.",
        x=_akse(lav, hoy, 4, "", lambda v: _akse_pst(v / 100)),
        legend=(("kat1", "Nettoinnflytting"), ("kat2", "Fødselsoverskudd")),
        link=LENKE,
        caption=f"Bidrag til befolkningsvekst, i prosent av folketallet 1.1.{aar_start}. "
        "Der fødselsoverskuddet er negativt går søylen motsatt vei, fordi bidraget "
        "trekker veksten ned. Klikk på et fylke for å avgrense figurene over til det.",
        source="Kilde: SSB tabell 06913, fylkesserien. Summen av de to søylene er "
        "ikke helt lik totalen til høyre; differansen er restleddet SSB ikke fordeler.",
    )


# --------------------------------------------------------------------------
# Artikkel — notatet og den publiserte sida rendres begge herfra
# --------------------------------------------------------------------------
def _fylkesperiode(
    fylke_aar: pl.DataFrame, vekst: pl.DataFrame, aar_start: int, aar_slutt: int
) -> pl.DataFrame:
    """Fylkestall for perioden, hentet fra fylkesserien.

    Ikke summert opp fra kommunene, selv om det hadde vært enklere. De to
    gir ulike svar før 2020: historikken til kommuner som ble delt det året
    ligger hos SSB i en samlekategori som ikke er noen kommune, og faller
    dermed ut av en kommunesummering. Fylkesserien har dem med, og er den
    som stemmer med Norges folketall.
    """
    niva = (
        fylke_aar.filter(pl.col("aar").is_in([aar_start, aar_slutt]))
        .pivot(on="aar", index=["fylkesnummer", "fylke"], values="folkemengde")
        .rename({str(aar_start): "folkemengde_start", str(aar_slutt): "folkemengde_slutt"})
    )
    strom = (
        fylke_aar.filter((pl.col("aar") >= aar_start) & (pl.col("aar") < aar_slutt))
        .group_by("fylkesnummer")
        .agg(
            pl.col("fodselsoverskudd").sum().alias("fodselsoverskudd_sum"),
            pl.col("nettoinnflytting").sum().alias("nettoinnflytting_sum"),
        )
    )
    antall = vekst.group_by("fylkesnummer").agg(pl.len().alias("kommuner"))
    return (
        niva.join(strom, on="fylkesnummer")
        .join(antall, on="fylkesnummer", how="left")
        .with_columns((pl.col("folkemengde_slutt") - pl.col("folkemengde_start")).alias("vekst"))
        .with_columns((pl.col("vekst") / pl.col("folkemengde_start")).alias("vekst_pst"))
        .sort("vekst_pst", descending=True)
    )


def artikkel(
    vekst: pl.DataFrame,
    fylke: pl.DataFrame,
    periode: str,
    proveniens: dict[str, str],
) -> publish.Article:
    """Sakspakken som struktur. Notatet og nettsida rendres begge fra denne.

    Alt som skal stå i teksten regnes ut her. Publiseringslaget regner
    ingenting — det får ferdig formaterte strenger, og kan derfor ikke
    komme til å vise et annet tall enn det som står i CSV-en.
    """
    alle = vekst
    sml = vekst.filter(pl.col("sammenlignbar"))
    utelatt = vekst.filter(~pl.col("sammenlignbar")).sort(
        "grenseavvik_maks_pst", descending=True
    )
    komplett = vekst.filter(pl.col("aar_uten_folketall") == 0)
    mangler = vekst.filter(pl.col("aar_uten_folketall") > 0)

    # Landstallene tas fra fylkestabellen, ikke fra kommunesummen. Se
    # _fylkesperiode: kommunesummen er ikke komplett før 2020.
    start = int(fylke["folkemengde_start"].sum())
    slutt = int(fylke["folkemengde_slutt"].sum())
    fodsel = int(fylke["fodselsoverskudd_sum"].sum())
    flytting = int(fylke["nettoinnflytting_sum"].sum())
    landsvekst = (slutt - start) / start
    ufordelt = start - int(alle["folkemengde_start"].sum())

    topp = sml.sort("vekst_pst", descending=True).row(0, named=True)
    bunn = sml.sort("vekst_pst").row(0, named=True)
    nedgang = sml.filter(pl.col("vekst") < 0).height
    under_snitt = sml.filter(pl.col("vekst_pst") < landsvekst).height
    neg_fodsel = sml.filter(pl.col("fodselsoverskudd_sum") < 0).height
    baaret_av_flytting = sml.filter(
        (pl.col("vekst") > 0) & (pl.col("nettoinnflytting_sum") > pl.col("vekst"))
    ).height

    aar_start = int(vekst["aar_start"][0])
    aar_slutt = int(vekst["aar_slutt"][0])
    utenfor_kilde = (
        f"Kilde: SSB tabell {TABELL}. Kommuner med grenseendring over "
        f"{_pst(TOLERANSE).lstrip('+')} av folketallet er holdt utenfor."
    )

    funn = publish.Section(
        "Funn",
        (
            publish.Stats(
                (
                    publish.Stat(
                        _antall(slutt - start), "Flere innbyggere", f"{periode}"
                    ),
                    publish.Stat(_pst(landsvekst), "Vekst i Norge", "over perioden"),
                    publish.Stat(
                        f"{flytting / (slutt - start) * 100:.0f} %",
                        "Av veksten er flytting",
                        f"{fodsel / (slutt - start) * 100:.0f} % er fødselsoverskudd",
                    ),
                    publish.Stat(
                        str(nedgang),
                        "Kommuner med nedgang",
                        f"av {sml.height} sammenlignbare",
                    ),
                )
            ),
            publish.Findings(
                (
                    f"Norge vokste fra {_antall(start)} til {_antall(slutt)} innbyggere, "
                    f"{_antall(slutt - start)} personer eller {_pst(landsvekst)}.",
                    f"Veksten er flytting, ikke fødsler: av de {_antall(slutt - start)} "
                    f"nye innbyggerne kommer {_antall(flytting)} fra nettoinnflytting og "
                    f"{_antall(fodsel)} fra fødselsoverskudd — "
                    f"{flytting / (slutt - start) * 100:.0f} mot "
                    f"{fodsel / (slutt - start) * 100:.0f} prosent. De siste "
                    f"{_antall(slutt - start - flytting - fodsel)} er restleddet SSB "
                    "ikke fordeler.",
                    f"Fødselsoverskuddet er negativt i {neg_fodsel} av {sml.height} "
                    f"sammenlignbare kommuner. I {baaret_av_flytting} kommuner er "
                    "nettoinnflyttingen alene større enn hele veksten — de vokser altså "
                    "*på tross av* at det dør flere enn det fødes.",
                    f"Veksten er skjevt fordelt: {under_snitt} av {sml.height} kommuner "
                    f"vokste saktere enn landet, og {nedgang} hadde direkte nedgang.",
                    f"Sterkest vekst: **{topp['kommune']}** ({kort_navn(topp['fylke'])}), "
                    f"{_pst(topp['vekst_pst'])} — men fra "
                    f"{_antall(topp['folkemengde_start'])} innbyggere. Svakest: "
                    f"**{bunn['kommune']}** ({kort_navn(bunn['fylke'])}), "
                    f"{_pst(bunn['vekst_pst'])}.",
                    f"Fylkesvis spenner det fra {_pst(fylke['vekst_pst'].max())} i "
                    f"{kort_navn(fylke.row(0, named=True)['fylke'])} til "
                    f"{_pst(fylke['vekst_pst'].min())} i "
                    f"{kort_navn(fylke.row(-1, named=True)['fylke'])}.",
                )
            ),
            _graf_komponenter(sml, utenfor_kilde),
            # Rangeringen bærer vekst_topp_bunn.png som fallback, og erstatter
            # den dermed framfor å komme i tillegg til den. En leser uten
            # skript ser nøyaktig den figuren hen så før; en leser med skript
            # får hele rangeringen i stedet for de tjue i hver ende.
            _graf_rangstripe(sml, utenfor_kilde),
        ),
    )

    fylker = publish.Section(
        "Fylker",
        (
            publish.Table(
                columns=(
                    "Fylke",
                    "Kommuner",
                    f"1.1.{aar_start}",
                    f"1.1.{aar_slutt}",
                    "Vekst",
                    "Herav flytting",
                ),
                align=("left", "right", "right", "right", "right", "right"),
                rows=tuple(
                    (
                        kort_navn(rad["fylke"]),
                        str(rad["kommuner"]),
                        _antall(rad["folkemengde_start"]),
                        _antall(rad["folkemengde_slutt"]),
                        _pst(rad["vekst_pst"]),
                        _antall(rad["nettoinnflytting_sum"]),
                    )
                    for rad in fylke.iter_rows(named=True)
                ),
                caption="Klikk på en kolonneoverskrift for å sortere.",
            ),
            _graf_fylke(fylke, aar_start),
        ),
    )

    aar_for_aar = publish.Section(
        "År for år",
        (
            publish.Figure(
                "aarlig_utvikling.png",
                alt="Tre paneler med én tynn grå linje per kommune, median og "
                "persentilbånd lagt over.",
                caption="Samlet tilvekst, nettoinnflytting og fødselsoverskudd, år for "
                "år. Panelene deler y-akse med vilje: fødselsoverskuddet holder seg "
                "innenfor et par prosent i alle kommuner alle år, mens flyttingen "
                "spriker. Med hver sin akse ville de sett like ut.",
                source="Kilde: SSB tabell 06913. «Hele landet» er summen av endringene "
                "delt på samlet folketall, ikke medianen av kommunene.",
                width="full",
            ),
            publish.Figure(
                "aarlig_ekstremer.png",
                alt="Samme tre komponenter, men bare de fem høyeste og fem laveste "
                "kommunene, navngitt.",
                caption=f"Spaghettigrafen over viser fordelingen og skjuler kommunene; "
                f"denne gjør det motsatte. Utvalget er de {N_EKSTREM} høyeste og laveste "
                "på kumulativ rate over hele perioden, ikke på enkeltår.",
                source="Kilde: SSB tabell 06913. Hvert panel har sin egen y-akse. Bare "
                "sammenlignbare kommuner.",
                width="full",
            ),
        ),
    )

    metode = publish.Section(
        "Metode",
        (
            publish.Findings(
                (
                    f"Kilde: SSB tabell {TABELL}, «{proveniens['label']}». "
                    f"SSB oppdaterte tabellen {proveniens['updated'][:10]}; "
                    f"hentet {proveniens['fetched_at'][:19]}Z, "
                    f"sha256 {proveniens['sha256'][:12]}…",
                    f"Modellene `{MODEL_AAR}`, `{MODEL_FYLKE}` og `{MODEL_VEKST}`, "
                    f"bygget av statman {proveniens['bygget'][:19].replace('T', ' ')}Z. "
                    "Råversjonen over er den byggeloggen oppgir, ikke den som "
                    "tilfeldigvis er nyest nå.",
                    "Kommuneinndeling: SSBs kodeliste `agg_KommSummerHist` («Kommuner "
                    "2024, sammenslåtte tidsserier»). Den summerer historikken til "
                    "sammenslåtte kommuner opp til dagens grenser, så kommunereformene "
                    "i 2018 og 2020 gir ikke seriebrudd. Fylkestallene bruker "
                    "`agg_KommFylkerHist`, som gjør det samme for fylker — ikke "
                    "`agg_Fylker2024`, som bare har tallene for fylkene slik de faktisk "
                    "het det året og summerer seg til 1,5 millioner i 2011.",
                    "Kodelista reverserer derimot ikke *delinger*, og fanger ikke "
                    "grensejusteringer. Vi finner dem i stedet i tallene: der endringen "
                    "i folkemengde ikke er lik folketilveksten SSB oppgir, har grensene "
                    "flyttet seg. Differansen ligger i kolonnen `grenseavvik`.",
                    "Vi krever ikke at avviket er null, men at det største enkeltavviket "
                    f"er under {_pst(TOLERANSE).lstrip('+')} av folketallet. Uten en "
                    "toleranse ville en grensejustering på 29 personer kastet Drammen ut "
                    "av statistikken. Kommuner over terskelen er merket "
                    "`sammenlignbar = false` og holdt utenfor rangering og topplister; "
                    "de nøyaktige avvikene står i `grenseavvik_sum` og "
                    "`grenseavvik_maks_pst` for alle kommuner.",
                    f"Det ga {utelatt.height} utelatte kommuner av {alle.height}.",
                    f"Kontroll: for de {komplett.height} kommunene som har folketall "
                    "hele perioden, summerer grenseavvikene seg til "
                    f"{_fortegn(komplett['grenseavvik_sum'].sum())} personer. "
                    "Grensejusteringer flytter folk mellom kommuner, så summen skal "
                    f"være null. De resterende "
                    f"{_antall(mangler['grenseavvik_sum'].sum())} tilhører de "
                    f"{mangler.height} kommunene som ble dannet av delte kommuner i "
                    "2020, og er de samme personene som mangler i kommunetabellen før "
                    "det året.",
                )
            ),
            publish.Table(
                columns=(
                    "Kommune",
                    "Fylke",
                    "Grenseavvik",
                    "Største enkeltavvik",
                    "Hva som skjedde",
                ),
                align=("left", "left", "right", "right", "left"),
                rows=tuple(
                    (
                        rad["kommune"],
                        kort_navn(rad["fylke"]),
                        _fortegn(rad["grenseavvik_sum"]),
                        # Kommuner uten folketall å dele på har ingen andel å vise.
                        f"{rad['grenseavvik_maks_pst'] * 100:.1f} %".replace(".", ",")
                        if rad["grenseavvik_maks_pst"]
                        else "—",
                        _forklaring(rad),
                    )
                    for rad in utelatt.iter_rows(named=True)
                ),
                caption=f"De {utelatt.height} kommunene som er holdt utenfor "
                "rangeringen, og hvorfor.",
            ),
            publish.Findings(
                (
                    f"**{_antall(ufordelt)} personer mangler i kommunetabellen i "
                    f"{aar_start}.** Kommuner som ble *delt* i 2020 — Tysfjord og "
                    "Snillfjord — har en historikk som ikke lar seg tilordne én kommune "
                    "i dagens inndeling. SSB legger den i samlekategorien «Delte "
                    "kommuner og uoppgitt», som ikke er noen kommune og derfor ikke er "
                    f"med her. Summen av de {alle.height} kommunene er altså "
                    f"{_antall(ufordelt)} lavere enn Norges folketall til og med 2019, "
                    "og null lavere fra 2020. Landstallene og fylkestabellen her er "
                    "hentet fra fylkesserien, som har dem med.",
                    "Ingen justering for at kommuner er ulike i størrelse. Prosentvekst "
                    "og absolutt vekst gir to forskjellige topplister; CSV-en har begge.",
                )
            ),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker=f"Befolkning · SSB tabell {TABELL}",
        title=f"Befolkningsvekst i norske kommuner, {periode}",
        lead=(
            f"Alle {alle.height} kommuner i 2024-inndelingen. Folkemengde "
            f"1.1.{aar_start} målt mot 1.1.{aar_slutt}. Det egentlige arbeidet i denne "
            "saken er ikke å regne ut prosentvekst, men å vite hvilke kommuner man "
            "*ikke* kan regne prosentvekst for."
        ),
        published=PUBLISERT,
        sections=(funn, fylker, aar_for_aar, metode),
        caveats=METRICS,
        provenance={
            "Kilde": f"SSB tabell {TABELL} — {proveniens['label']}",
            "Oppdatert": proveniens["updated"][:10],
            "Hentet": proveniens["fetched_at"][:19] + "Z",
            "sha256": proveniens["sha256"],
            "Kodeliste": "agg_KommSummerHist · agg_KommFylkerHist",
            "Modeller": f"{MODEL_AAR} · {MODEL_FYLKE} · {MODEL_VEKST}",
            "Bygget": proveniens["bygget"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "alle kommuner, alle kolonner"),
            ("vekst_topp_bunn.png", "topp og bunn på prosentvekst"),
            ("aarlig_utvikling.png", "årlig rate per kommune, tre paneler med felles akse"),
            ("aarlig_ekstremer.png", "de fem høyeste og laveste per komponent, navngitt"),
            ("komponenter.png", "fødselsoverskudd mot nettoinnflytting"),
            ("fylke.png", "fylkesvis vekst delt i komponenter"),
        ),
    )


# Hva som faktisk skjedde, for de tilfellene som er verdt å navngi. Resten
# får en forklaring utledet av tallene. Vi dikter ikke opp årsaker vi ikke
# har sjekket — «grensene flyttet seg dette året» er alt dataene sier.
_HENDELSER: Final[dict[str, str]] = {
    "1508": "Haram skilt ut igjen 1.1.2024",
    "1580": "Skilt ut fra Ålesund 1.1.2024, egen kommune også før 2020",
    "1806": "Ny kommune 2020 av Narvik, Ballangen og deler av Tysfjord",
    "1875": "Ny kommune 2020 av Hamarøy og deler av Tysfjord",
    "5055": "Ny kommune 2020 av Hemne, Halsa og deler av Snillfjord",
    "5056": "Utvidet 2020 med deler av Snillfjord",
    "5059": "Ny kommune 2020 av Orkdal, Meldal m.fl. og deler av Snillfjord",
    "3905": "Stokke delt mellom Tønsberg og Sandefjord 1.1.2017",
    "3907": "Stokke delt mellom Tønsberg og Sandefjord 1.1.2017",
}


def _forklaring(rad: dict) -> str:
    """Navngitt hendelse hvis vi har den, ellers det tallene faktisk sier."""
    kjent = _HENDELSER.get(rad["kommunenummer"])
    if kjent:
        return kjent
    if rad["aar_uten_folketall"]:
        return f"Ingen folketall for {int(rad['aar_uten_folketall'])} av årene"
    return f"Grensejustering 1.1.{int(rad['grenseavvik_maks_aar']) + 1}"


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    vekst = io.load(MODEL_VEKST)
    sml = vekst.filter(pl.col("sammenlignbar"))

    aar_start = int(vekst["aar_start"][0])
    aar_slutt = int(vekst["aar_slutt"][0])
    periode = f"{aar_start}–{aar_slutt - 1}"
    fylke = _fylkesperiode(io.load(MODEL_FYLKE), vekst, aar_start, aar_slutt)
    aar_df = io.load(MODEL_AAR)

    # Proveniensen hentes fra byggeloggen, ikke ved å slå opp nyeste rådata
    # på nytt. Nyeste kan ha blitt en annen siden modellene ble bygget, og
    # da ville notatet oppgitt en henting som ikke ga tallene i CSV-en.
    bygg = io.read_manifest(MODEL_VEKST)
    raa = bygg["raw"][RAW_KOMMUNE]
    versjon = io.raw_version_dir(RAW_KOMMUNE, raa["version"])
    proveniens = {**jsonstat.header(io.raw_data_file(versjon)), **raa, "bygget": bygg["built_at"]}

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    # Kommunenummeret som sekundærnøkkel: de 34 kommunene uten rangering har
    # alle vekst_pst = null, og uten et tiebreak kommer de i vilkårlig
    # rekkefølge. Da endrer den publiserte CSV-en seg for hvert bygg uten at
    # ett eneste tall er annerledes.
    vekst.sort(
        ["vekst_pst", "kommunenummer"], descending=[True, False], nulls_last=True
    ).write_csv(csv_path)

    figurer = [
        _plot_topp_bunn(sml, target / "vekst_topp_bunn.png", periode, aar_slutt),
        _plot_aarlig(aar_df, target / "aarlig_utvikling.png", periode),
        _plot_ekstremer(aar_df, vekst, target / "aarlig_ekstremer.png", periode),
        _plot_komponenter(sml, target / "komponenter.png", periode),
        _plot_fylke(fylke, target / "fylke.png", periode, aar_start),
    ]

    art = artikkel(vekst, fylke, periode, proveniens)
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
