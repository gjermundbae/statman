"""Ende-til-ende-eksempel: syntetisk kraftpris -> sakspakke i output/.

Poenget med eksempelet er ikke grafen. Det er å vise formen på en sakspakke:
et datasett, en graf og et notat der funn, metode og forbehold står sammen,
og der forbeholdene er hentet fra katalogen i stedet for å bli skrevet på nytt
hver gang.

Notatet skrives ikke for hånd. ``artikkel()`` bygger en
:class:`statman.publish.Article`, og både ``notat.md`` og en eventuell
publisert side rendres fra den — så de kan ikke gli fra hverandre.

Kjør:  uv run statman example
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, publish  # noqa: E402
from statman.sources import synthetic  # noqa: E402

MODEL = "mart.kraftpris_maaned"
SLUG = "kraftpris_syntetisk"
METRICS = ("kraftpris_nominell", "kraftpris_realt", "kraftpris_endring_12m")

# Byggemål for `statman example kraftpris`. clean-modellene er oppstrøms.
MODELS = [MODEL]


def ingest() -> dict[str, Path]:
    """Generer den syntetiske kilden. Ingen nettverk."""
    return synthetic.ingest()

# strftime("%B") følger systemlokalet og gir engelske månedsnavn på de fleste
# maskiner. Vi hardkoder heller enn å rote med locale, som er global state og
# oppfører seg ulikt på macOS og Linux.
# Flytt denne til statman/ når sakspakke nummer to trenger den.
MAANEDER: tuple[str, ...] = (
    "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
)


def month_label(day: dt.date) -> str:
    """``date(2025, 12, 1)`` -> ``"desember 2025"``."""
    return f"{MAANEDER[day.month - 1]} {day.year}"


def _plot(df: pl.DataFrame, path: Path, ref_month: str) -> Path:
    areas = sorted(df["prisomrade"].unique().to_list())
    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    for area in areas:
        sub = df.filter(pl.col("prisomrade") == area).sort("month")
        months = sub["month"].to_list()
        ax_top.plot(months, sub["ore_nominell"].to_list(), linewidth=1.4, label=area)
        ax_bottom.plot(months, sub["ore_faste_kroner"].to_list(), linewidth=1.4, label=area)

    ax_top.set_title("Nominell kraftpris — løpende kroner", loc="left", fontsize=11)
    ax_bottom.set_title(
        f"Kraftpris i faste kroner — {ref_month}-kroner", loc="left", fontsize=11
    )
    for ax in (ax_top, ax_bottom):
        ax.set_ylabel("øre/kWh")
        ax.grid(True, alpha=0.25, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    ax_bottom.legend(ncols=len(areas), frameon=False, fontsize=9, loc="upper left")

    fig.suptitle(
        "SYNTETISKE DATA — kraftpris per prisområde",
        x=0.01, ha="left", fontsize=14, fontweight="bold",
    )
    fig.text(
        0.01, 0.005,
        "Kilde: statman.sources.synthetic. Ikke ekte statistikk.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _tall(verdi: float, desimaler: int = 0) -> str:
    return f"{verdi:,.{desimaler}f}".replace(",", " ").replace(".", ",")


def artikkel(df: pl.DataFrame, ref_month: str) -> publish.Article:
    """Sakspakken som struktur. Notatet og nettsida rendres begge fra denne."""
    peak = df.sort("ore_faste_kroner", descending=True).row(0, named=True)
    first_year = df.filter(pl.col("month").dt.year() == df["month"].dt.year().min())
    last_year = df.filter(pl.col("month").dt.year() == df["month"].dt.year().max())
    aar_start = int(first_year["month"].dt.year().min())
    aar_slutt = int(last_year["month"].dt.year().max())
    start = float(first_year["ore_faste_kroner"].mean())
    end = float(last_year["ore_faste_kroner"].mean())

    bygg = io.read_manifest(MODEL)

    return publish.Article(
        slug=SLUG,
        kicker="Syntetiske data · testkjede",
        title="Kraftpris per prisområde",
        lead=(
            "Tallene er oppdiktet, problemet er ekte: nominelle kroner fra ulike år "
            "kan ikke sammenlignes uten å deflateres. Saken finnes for å vise formen "
            "på en sakspakke, ikke for å si noe om strømprisen."
        ),
        published=bygg["built_at"][:10],
        sections=(
            publish.Section(
                "Funn",
                (
                    publish.Stats(
                        (
                            publish.Stat(
                                f"{_tall(peak['ore_faste_kroner'])} øre",
                                "Høyeste realpris i serien",
                                f"{peak['prisomrade']}, {month_label(peak['month'])}",
                            ),
                            publish.Stat(
                                f"{_tall(start, 1)} øre", f"Snitt {aar_start}", "per kWh"
                            ),
                            publish.Stat(
                                f"{_tall(end, 1)} øre", f"Snitt {aar_slutt}", "per kWh"
                            ),
                            publish.Stat(
                                f"{(end / start - 1) * 100:+.0f} %".replace(".", ","),
                                "Endring i faste kroner",
                                f"{aar_start} mot {aar_slutt}",
                            ),
                        )
                    ),
                    publish.Findings(
                        (
                            f"Høyeste realpris i serien: **{_tall(peak['ore_faste_kroner'])} "
                            f"øre/kWh** i {peak['prisomrade']}, {month_label(peak['month'])}.",
                            f"Snitt realpris {aar_start}: {_tall(start, 1)} øre/kWh. "
                            f"Snitt {aar_slutt}: {_tall(end, 1)} øre/kWh "
                            f"({(end / start - 1) * 100:+.0f} %).",
                            "Utslaget er systematisk større i de sørlige prisområdene "
                            "enn i de nordlige.",
                        )
                    ),
                    publish.Figure(
                        "kraftpris.png",
                        alt="To paneler: nominell kraftpris øverst, faste kroner nederst, "
                        "én linje per prisområde.",
                        caption="Samme serie i løpende og faste kroner. Forskjellen mellom "
                        "panelene er hele poenget med saken.",
                        source=f"Kilde: statman.sources.synthetic. Faste {ref_month}-kroner.",
                    ),
                ),
            ),
            publish.Section(
                "Metode",
                (
                    publish.Findings(
                        (
                            f"Kilde: modellen `{MODEL}`, bygget av statman.",
                            f"Nominelle priser deflatert med KPI til {ref_month}-kroner.",
                            "Ingen sesongjustering. Kraftpris har sterk og velkjent "
                            "årssyklus; sammenlign måned mot samme måned året før.",
                        )
                    ),
                    publish.Prose(
                        "**Dette er syntetiske data laget for å teste pipelinen. "
                        "Ikke publiser dem.**"
                    ),
                ),
            ),
        ),
        caveats=METRICS,
        provenance={
            "Kilde": "statman.sources.synthetic — ikke ekte statistikk",
            "Modell": MODEL,
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
            "Rader": str(bygg["rows"]),
            "Referansemåned": ref_month,
        },
        files=(
            ("kraftpris.csv", "hele serien, alle prisområder og kolonner"),
            ("kraftpris.png", "nominell og real kraftpris per prisområde"),
        ),
    )


def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    df = io.load(MODEL)
    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    ref_month = month_label(df["month"].max())
    csv_path = target / "kraftpris.csv"
    df.write_csv(csv_path)
    png_path = _plot(df, target / "kraftpris.png", ref_month)

    art = artikkel(df, ref_month)
    art.validate(target)
    return [
        csv_path,
        png_path,
        publish.markdown.write(art, target / "notat.md"),
        art.write(target),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
