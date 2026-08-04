"""Ende-til-ende: drikkevannskvaliteten i Farrisvannet over tid.

Utløst av en mulighetsvurdering av fiskebestandsdata i Farris — den var for
tynn til noe som helst (se prosjektloggen), men jakten på den avdekket at
Vestfold Vann IKS' eget overvåkingsprogram for drikkevannskilden *er*
maskinlesbart, via Vannmiljøs faktaark-eksport
(``vannmiljofaktaark.miljodirektoratet.no``, se
``statman/sources/vannmiljo.py``).

    vannmiljo.fetch_all_farris()  ->  raw/vannmiljo/farris_{bakkepollen,eikenesfjorden,nesfjorden}
      -> clean.vannmiljo_farris
      -> mart.farris_vannkvalitet_dato, mart.farris_algeblomst_aar
      -> output/farris_vannkvalitet/     (sakspakke)
      -> statman publish farris_vannkvalitet  -> docs/   (artikkel)

Denne saken er annerledes enn de andre i prosjektet: ingen korrelasjon,
ingen p-verdi, ingen forskyvningstabell. Oppdraget var ren utvikling over
tid, fortalt gjennom tre grafer — sesongsyklusen i vannfargen, bakterienes
årlige sesongtopper, og de årlige blågrønnalge-toppmålingene. Der de andre
sakene tester om en sammenheng holder, tester denne ingenting; den viser
fram et mønster som allerede er der i dataene.

Kjør:  uv run statman example farris
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, publish  # noqa: E402
from statman.sources import vannmiljo  # noqa: E402

SLUG: Final[str] = "farris_vannkvalitet"

MODEL_VANNKVALITET: Final[str] = "mart.farris_vannkvalitet_dato"
MODEL_ALGEBLOMST: Final[str] = "mart.farris_algeblomst_aar"
MODELS: Final[list[str]] = [MODEL_VANNKVALITET, MODEL_ALGEBLOMST]

METRICS: Final[tuple[str, ...]] = (
    "farris_fargetall",
    "farris_turbiditet",
    "farris_koliforme_bakterier",
    "farris_e_coli",
    "farris_cyanobakterier_aar",
)

FARGE_AAR_CMAP: Final[str] = "viridis"
FARGE_KOLI: Final[str] = "#8a5a2b"
FARGE_EKOLI: Final[str] = "#c0392b"
FARGE_LOKALITET: Final[dict[str, str]] = {
    "Farris, Eikenesfjorden": "#1f6f54",
    "Farris, Nesfjorden": "#2f6690",
}


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent alle tre Vannmiljø-lokalitetene. Uavhengige av hverandre."""
    return vannmiljo.fetch_all_farris()


# --------------------------------------------------------------------------
# Grafer
# --------------------------------------------------------------------------
def _plot_sesongsyklus_farge(df: pl.DataFrame, path: Path) -> Path:
    """Fargetall etter dag i året, én linje per år — sesongbølgen og hvordan den flytter seg."""
    d = df.with_columns(pl.col("dato").dt.ordinal_day().alias("dag_i_aaret")).sort(
        "aar", "dag_i_aaret"
    )
    aar_liste = sorted(d["aar"].unique().to_list())
    cmap = plt.get_cmap(FARGE_AAR_CMAP)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    for i, aar in enumerate(aar_liste):
        rad = d.filter(pl.col("aar") == aar)
        farge = cmap(i / max(len(aar_liste) - 1, 1))
        ax.plot(
            rad["dag_i_aaret"].to_list(),
            rad["fargetall_mg_pt_l"].to_list(),
            color=farge, linewidth=1.6, marker="o", markersize=4, alpha=0.85,
            label=str(aar),
        )

    ax.set_xlim(90, 320)
    ax.set_xticks([91, 121, 152, 182, 213, 244, 274, 305])
    ax.set_xticklabels(["apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov"])
    ax.set_ylabel("Fargetall (mg Pt/l), øverste meter")
    ax.grid(True, alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(
        "Samme bølge, år etter år — lysere om sommeren, mørkere vår og høst",
        loc="left", fontsize=14, fontweight="bold",
    )
    ax.legend(
        title="År", ncols=2, frameon=True, framealpha=0.9, edgecolor="none",
        fontsize=8, title_fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.02),
    )
    fig.text(
        0.01, 0.005,
        "Kilde: Miljødirektoratet, Vannmiljø — Vestfold Vann IKS' overvåking ved Bakkepollen, "
        "Farris. Én linje per år, 2011-2022. Prøver tas bare april-november.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.03, 0.84, 0.95))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _plot_bakterier(df: pl.DataFrame, path: Path) -> Path:
    """Koliforme bakterier og E. coli over hele perioden, logaritmisk akse — toppene kommer sensommer/høst."""
    d = df.sort("dato")
    x = d["dato"].to_list()

    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.bar(x, d["koliforme_bakterier_per_100ml"].to_list(), width=12, color=FARGE_KOLI, alpha=0.8, label="Koliforme bakterier")
    ax.plot(x, d["e_coli_per_100ml"].to_list(), color=FARGE_EKOLI, linewidth=1.4, marker="o", markersize=3.5, label="E. coli")

    ax.set_yscale("log")
    ax.set_ylabel("Antall per 100 ml, øverste meter (logaritmisk skala)")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(True, alpha=0.2, linewidth=0.6, which="both")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=True, framealpha=0.9, edgecolor="none", fontsize=9, loc="upper left")
    ax.set_title(
        "Bakterietallene ligger nesten alltid lavt — og hopper opp sensommer og høst",
        loc="left", fontsize=14, fontweight="bold",
    )
    fig.text(
        0.01, 0.005,
        "Kilde: Vannmiljø — Vestfold Vann IKS, Bakkepollen i Farris, 2011-2022. Råvann fra "
        "innsjøen, ikke ferdig renset drikkevann fra springen.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _plot_algeblomst(df: pl.DataFrame, path: Path) -> Path:
    """Årlig cyanobakterie-maks, to målepunkter, grupperte stolper — år med mye og lite blomstring."""
    d = (
        df.drop_nulls("cyano_maks_mg_l")
        .with_columns((pl.col("cyano_maks_mg_l") * 1000).alias("cyano_ug_l"))
        .sort("aar")
    )
    aar_liste = sorted(d["aar"].unique().to_list())
    lokaliteter = sorted(d["lokalitet"].unique().to_list())

    fig, ax = plt.subplots(figsize=(12, 6.5))
    bredde = 0.38
    x_pos = {aar: i for i, aar in enumerate(aar_liste)}
    for j, lok in enumerate(lokaliteter):
        rad = d.filter(pl.col("lokalitet") == lok).sort("aar")
        xs = [x_pos[a] + (j - 0.5) * bredde for a in rad["aar"].to_list()]
        ax.bar(
            xs, rad["cyano_ug_l"].to_list(), width=bredde * 0.92,
            color=FARGE_LOKALITET.get(lok, "0.5"), label=lok.replace("Farris, ", ""),
        )

    ax.set_xticks(list(x_pos.values()))
    ax.set_xticklabels([str(a) for a in aar_liste], rotation=45, ha="right")
    ax.set_ylabel("Cyanobakterier, årlig maksmåling (µg/l biomasse)")
    ax.grid(True, alpha=0.2, linewidth=0.6, axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=True, framealpha=0.9, edgecolor="none", fontsize=9, loc="upper right")
    ax.set_title(
        "Blågrønnalgene svinger stort fra år til år — uten en klar retning",
        loc="left", fontsize=14, fontweight="bold",
    )
    fig.text(
        0.01, 0.005,
        "Kilde: Vannmiljø — Vestfold Vann IKS, Eikenesfjorden og Nesfjorden i Farris. Én måling "
        "i året. Manglende år er ikke null, bare ikke målt.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# Artikkel
# --------------------------------------------------------------------------
def artikkel(
    vann: pl.DataFrame,
    alge: pl.DataFrame,
    bygg: dict,
) -> publish.Article:
    n_datoer = vann.height
    aar_min, aar_max = vann["aar"].min(), vann["aar"].max()
    farge_min, farge_max = vann["fargetall_mg_pt_l"].min(), vann["fargetall_mg_pt_l"].max()
    koli_maks = vann["koliforme_bakterier_per_100ml"].max()
    alge_maalt = alge.drop_nulls("cyano_maks_mg_l")
    n_algeaar = alge_maalt.height
    cyano_min = alge_maalt["cyano_maks_mg_l"].min() * 1000
    cyano_max = alge_maalt["cyano_maks_mg_l"].max() * 1000

    funn = publish.Section(
        "Funn",
        (
            publish.Stats(
                (
                    publish.Stat(str(n_datoer), "Prøvedatoer", f"{aar_min}-{aar_max}, april-november hvert år"),
                    publish.Stat(f"{farge_min:.0f}-{farge_max:.0f}", "Fargetall, spennet", "mg Pt/l, øverste meter"),
                    publish.Stat(f"{koli_maks:.0f}", "Høyeste bakterietall", "koliforme bakterier per 100 ml, én enkelt dato"),
                    publish.Stat(str(n_algeaar), "Årlige algemålinger", "to målepunkter, 2010-2025"),
                )
            ),
            publish.Findings(
                (
                    "**Vannfargen føler årstidene, ikke en langsiktig trend.** Hvert år tegner "
                    "samme bølge: lysere (lavere fargetall) om sommeren, mørkere vår og høst — "
                    "trolig humus og avrenning som følger nedbør og snøsmelting mer enn "
                    "temperaturen alene. Elleve år lagt oppå hverandre viser akkurat den samme "
                    "formen igjen og igjen, uten at noe år stikker klart av fra resten.",
                    "**Bakteriene ligger nesten alltid lavt, og hopper opp på samme tid av året.** "
                    "Koliforme bakterier og E. coli i råvannet er stort sett enkeltsifret gjennom "
                    "våren og tidlig sommer, men får gjentatte topper i august-oktober — mønsteret "
                    "går igjen år etter år, ikke bare én sommer. Dette er råvann rett fra "
                    "innsjøen; det sier ingenting om drikkevannet som faktisk kommer ut av "
                    "springen, som renses og desinfiseres etter dette prøvepunktet.",
                    "**Blågrønnalgene svinger mye fra år til år, uten en tydelig retning opp eller "
                    "ned.** Den årlige toppmålingen varierer nesten hundre ganger mellom det "
                    "roligste og det verste året i disse dataene — men verken de siste årene eller "
                    "de eldste dataene peker klart i én retning. Larvik kommune har omtalt "
                    "blågrønnalger i Farris som et tilbakevendende fenomen siden slutten av "
                    "1980-tallet; disse tallene dekker bare 2010 og framover, og bekrefter "
                    "svingningene uten å kunne si noe om utviklingen før den tid.",
                )
            ),
            publish.Figure(
                "sesongsyklus_farge.png",
                alt="Linjediagram med én linje per år (2011-2022), fargetall i mg Pt/l langs "
                "x-aksen april til november.",
                caption="Samme bølgeform gjentar seg år etter år: lysere sommer, mørkere vår og "
                "høst.",
                source="Kilde: Vannmiljø — Vestfold Vann IKS, Bakkepollen i Farris.",
                width="full",
            ),
            publish.Figure(
                "bakterier_tidslinje.png",
                alt="Stolpediagram (koliforme bakterier) og linje (E. coli) over hele perioden "
                "2011-2022, logaritmisk akse.",
                caption="Bakterietallene ligger nesten alltid lavt, og hopper opp sensommer og "
                "høst.",
                source="Kilde: Vannmiljø — Vestfold Vann IKS, Bakkepollen i Farris.",
                width="full",
            ),
            publish.Figure(
                "algeblomst_aar.png",
                alt="Grupperte stolper, cyanobakterier årlig maks 2010-2025, to målepunkter.",
                caption="Store forskjeller fra år til år, uten en klar retning over 15 år.",
                source="Kilde: Vannmiljø — Vestfold Vann IKS, Eikenesfjorden og Nesfjorden i Farris.",
                width="full",
            ),
        ),
    )

    metode = publish.Section(
        "Metode",
        (
            publish.Findings(
                (
                    "Alle tall er hentet fra Vannmiljøs offentlige faktaark-eksport "
                    "(`vannmiljofaktaark.miljodirektoratet.no`), som gir hver registrering "
                    "Vestfold Vann IKS har meldt inn for sitt overvåkingsprogram i Farris — "
                    "ikke et utvalg eller en oppsummering.",
                    "Farge, turbiditet og bakterietallene er fra ett målepunkt, Bakkepollen, og "
                    "bare øverste meter av et fullt dypprofil ned til 60 meter som tas ved hver "
                    "prøve. Cyanobakterie-tallene er fra to andre punkter, Eikenesfjorden og "
                    "Nesfjorden, én årlig måling hver.",
                    "Denne saken tester ingen sammenheng og regner ikke ut noen korrelasjon — "
                    "den viser fram tre mønstre som allerede ligger i tallene: en sesongsyklus, "
                    "en årlig svingning, og fraværet av en tydelig langsiktig trend i begge.",
                    f"Modellene `{MODEL_VANNKVALITET}` og `{MODEL_ALGEBLOMST}`, bygget av statman "
                    f"{bygg['built_at'][:19].replace('T', ' ')}Z.",
                    "Dette startet som en mulighetsvurdering av fiskebestandsdata i Farris — de "
                    "fantes ikke i noen brukbar form. Jakten på dem avdekket i stedet at "
                    "drikkevannsovervåkingen er både åpen og maskinlesbar, og det er den denne "
                    "saken bygger på.",
                )
            ),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker="Drikkevann · Vannmiljø, Vestfold Vann IKS",
        title="Farrisvannet gjennom elleve somre: samme bølge, ingen trend",
        lead=(
            f"{n_datoer} prøver fra {aar_min} til {aar_max} ved Vestfold Vann IKS' eget "
            "overvåkingspunkt i Farris tegner tre klare mønstre: vannfargen følger årstidene "
            "nesten identisk hvert år, bakterietallene hopper opp på samme tid av året igjen "
            "og igjen, og de årlige blågrønnalge-målingene svinger kraftig uten å flytte seg i "
            "noen bestemt retning over 15 år."
        ),
        published=bygg["built_at"][:10],
        sections=(funn, metode),
        caveats=METRICS,
        provenance={
            "Kilde": "Miljødirektoratet, Vannmiljø — vannmiljofaktaark.miljodirektoratet.no",
            "Oppdragsgiver (data)": "Vestfold Vann IKS",
            "Vannlokaliteter": "015-88038 (Bakkepollen), 015-84635 (Eikenesfjorden), 015-84636 (Nesfjorden)",
            "Modeller": f"{MODEL_VANNKVALITET} · {MODEL_ALGEBLOMST}",
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}_vannkvalitet.csv", "alle 78 prøvedatoer ved Bakkepollen, 2011-2022"),
            (f"{SLUG}_algeblomst.csv", "årlige cyanobakterie- og eutrofieringstall, 2010-2025"),
            ("sesongsyklus_farge.png", "fargetall etter dag i året, én linje per år"),
            ("bakterier_tidslinje.png", "koliforme bakterier og E. coli, hele perioden"),
            ("algeblomst_aar.png", "årlig cyanobakterie-maks, to målepunkter"),
        ),
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    vann = io.load(MODEL_VANNKVALITET).sort("dato")
    alge = io.load(MODEL_ALGEBLOMST).sort(["aar", "lokalitet"])
    bygg = io.read_manifest(MODEL_VANNKVALITET)

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_vann = target / f"{SLUG}_vannkvalitet.csv"
    vann.write_csv(csv_vann)
    csv_alge = target / f"{SLUG}_algeblomst.csv"
    alge.write_csv(csv_alge)

    figurer = [
        _plot_sesongsyklus_farge(vann, target / "sesongsyklus_farge.png"),
        _plot_bakterier(vann, target / "bakterier_tidslinje.png"),
        _plot_algeblomst(alge, target / "algeblomst_aar.png"),
    ]

    art = artikkel(vann, alge, bygg)
    art.validate(target)
    return [
        csv_vann,
        csv_alge,
        *figurer,
        publish.markdown.write(art, target / "notat.md"),
        art.write(target),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
