"""Ende-til-ende-eksempel: befolkningsvekst i alle norske kommuner 2011–2025.

Ekte tall fra SSB, hele veien fra API-kall til sakspakke. Kjeden er:

    ssb.fetch_table(06913)  ->  raw/ssb/06913_kommune
                                raw/ssb/06913_fylke
      -> clean.befolkning_kommune, clean.befolkning_fylke
      -> mart.befolkning_kommune_aar, mart.befolkning_fylke_aar
      -> mart.befolkningsvekst
      -> output/befolkningsvekst_kommune/

Det egentlige arbeidet i denne saken er ikke å regne ut prosentvekst. Det er
å vite hvilke kommuner man *ikke* kan regne prosentvekst for. Femten år
dekker to kommunereformer, én fylkesreform, én kommunedeling og et titalls
grensejusteringer. Se ``statman/models/mart_befolkning.py``.

Kjør:  uv run statman example befolkning
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import catalog, io, jsonstat  # noqa: E402
from statman.models.clean_ssb_befolkning import RAW_FYLKE, RAW_KOMMUNE, VARIABLER  # noqa: E402
from statman.models.mart_befolkning import PERIODE_AAR, TOLERANSE  # noqa: E402
from statman.sources import ssb  # noqa: E402

TABELL: Final[str] = "06913"
SLUG: Final[str] = "befolkningsvekst_kommune"
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

FARGE_VEKST: Final[str] = "#1f6f4a"
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
# Notat
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


def _notat(
    vekst: pl.DataFrame,
    fylke: pl.DataFrame,
    path: Path,
    periode: str,
    proveniens: dict[str, str],
) -> Path:
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

    lines = [
        f"# Befolkningsvekst i norske kommuner, {periode}",
        "",
        f"Alle {alle.height} kommuner i 2024-inndelingen. Folkemengde "
        f"1.1.{vekst['aar_start'][0]} målt mot 1.1.{vekst['aar_slutt'][0]}.",
        "",
        "## Funn",
        "",
        f"- Norge vokste fra {_antall(start)} til {_antall(slutt)} innbyggere, "
        f"{_antall(slutt - start)} personer eller {_pst(landsvekst)}.",
        f"- Veksten er flytting, ikke fødsler: av de {_antall(slutt - start)} nye innbyggerne "
        f"kommer {_antall(flytting)} fra nettoinnflytting og {_antall(fodsel)} fra "
        f"fødselsoverskudd — {flytting / (slutt - start) * 100:.0f} mot "
        f"{fodsel / (slutt - start) * 100:.0f} prosent. De siste "
        f"{_antall(slutt - start - flytting - fodsel)} er restleddet SSB ikke fordeler.",
        f"- Fødselsoverskuddet er negativt i {neg_fodsel} av {sml.height} sammenlignbare kommuner. "
        f"I {baaret_av_flytting} kommuner er nettoinnflyttingen alene større enn hele veksten — "
        "de vokser altså *på tross av* at det dør flere enn det fødes.",
        f"- Veksten er skjevt fordelt: {under_snitt} av {sml.height} kommuner vokste saktere enn "
        f"landet, og {nedgang} hadde direkte nedgang.",
        f"- Sterkest vekst: **{topp['kommune']}** ({kort_navn(topp['fylke'])}), "
        f"{_pst(topp['vekst_pst'])} — men fra {_antall(topp['folkemengde_start'])} innbyggere. "
        f"Svakest: **{bunn['kommune']}** ({kort_navn(bunn['fylke'])}), {_pst(bunn['vekst_pst'])}.",
        f"- Fylkesvis spenner det fra {_pst(fylke['vekst_pst'].max())} i "
        f"{kort_navn(fylke.row(0, named=True)['fylke'])} til "
        f"{_pst(fylke['vekst_pst'].min())} i "
        f"{kort_navn(fylke.row(-1, named=True)['fylke'])}.",
        "",
        "## Fylker",
        "",
        f"| Fylke | Kommuner | 1.1.{vekst['aar_start'][0]} | 1.1.{vekst['aar_slutt'][0]} "
        "| Vekst | Herav flytting |",
        "|---|--:|--:|--:|--:|--:|",
    ]
    for rad in fylke.iter_rows(named=True):
        lines.append(
            f"| {kort_navn(rad['fylke'])} | {rad['kommuner']} | "
            f"{_antall(rad['folkemengde_start'])} | {_antall(rad['folkemengde_slutt'])} | "
            f"{_pst(rad['vekst_pst'])} | {_antall(rad['nettoinnflytting_sum'])} |"
        )

    lines += [
        "",
        "## Metode",
        "",
        f"- Kilde: SSB tabell {TABELL}, «{proveniens['label']}». "
        f"SSB oppdaterte tabellen {proveniens['updated'][:10]}; "
        f"hentet {proveniens['fetched_at'][:19]}Z, sha256 {proveniens['sha256'][:12]}…",
        f"- Modellene `{MODEL_AAR}`, `{MODEL_FYLKE}` og `{MODEL_VEKST}`, bygget av statman "
        f"{proveniens['bygget'][:19].replace('T', ' ')}Z. Råversjonen over er den "
        "byggeloggen oppgir, ikke den som tilfeldigvis er nyest nå.",
        "- Kommuneinndeling: SSBs kodeliste `agg_KommSummerHist` («Kommuner 2024, "
        "sammenslåtte tidsserier»). Den summerer historikken til sammenslåtte kommuner "
        "opp til dagens grenser, så kommunereformene i 2018 og 2020 gir ikke seriebrudd. "
        "Fylkestallene bruker `agg_KommFylkerHist`, som gjør det samme for fylker — "
        "ikke `agg_Fylker2024`, som bare har tallene for fylkene slik de faktisk het "
        "det året og summerer seg til 1,5 millioner i 2011.",
        "- Kodelista reverserer derimot ikke *delinger*, og fanger ikke grensejusteringer. "
        "Vi finner dem i stedet i tallene: der endringen i folkemengde ikke er lik "
        "folketilveksten SSB oppgir, har grensene flyttet seg. Differansen ligger i "
        "kolonnen `grenseavvik`.",
        f"- Vi krever ikke at avviket er null, men at det største enkeltavviket er under "
        f"{_pst(TOLERANSE).lstrip('+')} av folketallet. Uten en toleranse ville en "
        "grensejustering på 29 personer kastet Drammen ut av statistikken. Kommuner over "
        "terskelen er merket `sammenlignbar = false` og holdt utenfor rangering og "
        "topplister; de nøyaktige avvikene står i `grenseavvik_sum` og "
        "`grenseavvik_maks_pst` for alle kommuner.",
        f"- Det ga {utelatt.height} utelatte kommuner av {alle.height}.",
        f"- Kontroll: for de {komplett.height} kommunene som har folketall hele perioden, "
        f"summerer grenseavvikene seg til {_fortegn(komplett['grenseavvik_sum'].sum())} "
        "personer. Grensejusteringer flytter folk mellom kommuner, så summen skal være "
        f"null. De resterende {_antall(mangler['grenseavvik_sum'].sum())} tilhører de "
        f"{mangler.height} kommunene som ble dannet av delte kommuner i 2020, og er de "
        "samme personene som mangler i kommunetabellen før det året.",
        "",
        "| Kommune | Fylke | Grenseavvik | Største enkeltavvik | Hva som skjedde |",
        "|---|---|--:|--:|---|",
    ]
    for rad in utelatt.iter_rows(named=True):
        # Kommuner uten folketall å dele på har ingen relativ andel å vise.
        andel = (
            f"{rad['grenseavvik_maks_pst'] * 100:.1f} %".replace(".", ",")
            if rad["grenseavvik_maks_pst"]
            else "—"
        )
        lines.append(
            f"| {rad['kommune']} | {kort_navn(rad['fylke'])} | "
            f"{_fortegn(rad['grenseavvik_sum'])} | {andel} | {_forklaring(rad)} |"
        )

    lines += [
        "",
        f"- **{_antall(ufordelt)} personer mangler i kommunetabellen i "
        f"{vekst['aar_start'][0]}.** Kommuner som ble *delt* i 2020 — Tysfjord og "
        "Snillfjord — har en historikk som ikke lar seg tilordne én kommune i dagens "
        "inndeling. SSB legger den i samlekategorien «Delte kommuner og uoppgitt», som "
        "ikke er noen kommune og derfor ikke er med her. Summen av de 357 kommunene er "
        f"altså {_antall(ufordelt)} lavere enn Norges folketall til og med 2019, og null "
        "lavere fra 2020. Landstallene og fylkestabellen i dette notatet er hentet fra "
        "fylkesserien, som har dem med.",
        "- Ingen justering for at kommuner er ulike i størrelse. Prosentvekst og "
        "absolutt vekst gir to forskjellige topplister; CSV-en har begge.",
        "",
        "## Forbehold",
        "",
    ]
    for key in METRICS:
        lines.append(catalog.metric(key).note())
        lines.append("")

    lines += [
        "## Filer",
        "",
        "- `befolkningsvekst_kommune.csv` — alle kommuner, alle kolonner.",
        "- `vekst_topp_bunn.png` — topp og bunn på prosentvekst.",
        "- `aarlig_utvikling.png` — årlig rate per kommune, tre paneler med felles akse.",
        "- `aarlig_ekstremer.png` — de fem høyeste og laveste per komponent, navngitt.",
        "- `komponenter.png` — fødselsoverskudd mot nettoinnflytting.",
        "- `fylke.png` — fylkesvis vekst delt i komponenter.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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

    csv_path = target / "befolkningsvekst_kommune.csv"
    vekst.sort("vekst_pst", descending=True, nulls_last=True).write_csv(csv_path)

    return [
        csv_path,
        _plot_topp_bunn(sml, target / "vekst_topp_bunn.png", periode, aar_slutt),
        _plot_aarlig(aar_df, target / "aarlig_utvikling.png", periode),
        _plot_ekstremer(aar_df, vekst, target / "aarlig_ekstremer.png", periode),
        _plot_komponenter(sml, target / "komponenter.png", periode),
        _plot_fylke(fylke, target / "fylke.png", periode, aar_start),
        _notat(vekst, fylke, target / "notat.md", periode, proveniens),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
