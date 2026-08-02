"""Ende-til-ende-eksempel: syntetisk kraftpris -> sakspakke i output/.

Poenget med eksempelet er ikke grafen. Det er å vise formen på en sakspakke:
et datasett, en graf og et notat der funn, metode og forbehold står sammen,
og der forbeholdene er hentet fra katalogen i stedet for å bli skrevet på nytt
hver gang.

Kjør:  uv run statman example
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import catalog, io  # noqa: E402
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


def _notat(df: pl.DataFrame, path: Path, ref_month: str) -> Path:
    peak = df.sort("ore_faste_kroner", descending=True).row(0, named=True)
    first_year = df.filter(pl.col("month").dt.year() == df["month"].dt.year().min())
    last_year = df.filter(pl.col("month").dt.year() == df["month"].dt.year().max())
    start = float(first_year["ore_faste_kroner"].mean())
    end = float(last_year["ore_faste_kroner"].mean())

    lines = [
        "# Kraftpris per prisområde (syntetiske data)",
        "",
        "## Funn",
        "",
        f"- Høyeste realpris i serien: **{peak['ore_faste_kroner']:.0f} øre/kWh** "
        f"i {peak['prisomrade']}, {month_label(peak['month'])}.",
        f"- Snitt realpris {first_year['month'].dt.year().min()}: {start:.1f} øre/kWh. "
        f"Snitt {last_year['month'].dt.year().max()}: {end:.1f} øre/kWh "
        f"({(end / start - 1) * 100:+.0f} %).",
        "- Utslaget er systematisk større i de sørlige prisområdene enn i de nordlige.",
        "",
        "## Metode",
        "",
        f"- Kilde: modellen `{MODEL}`, bygget av statman.",
        f"- Nominelle priser deflatert med KPI til {ref_month}-kroner.",
        "- Ingen sesongjustering. Kraftpris har sterk og velkjent årssyklus;"
        " sammenlign måned mot samme måned året før.",
        "",
        "## Forbehold",
        "",
    ]
    for key in METRICS:
        lines.append(catalog.metric(key).note())
        lines.append("")
    lines.append("**Dette er syntetiske data laget for å teste pipelinen. Ikke publiser dem.**")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    df = io.load(MODEL)
    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    ref_month = month_label(df["month"].max())
    csv_path = target / "kraftpris.csv"
    df.write_csv(csv_path)

    return [
        csv_path,
        _plot(df, target / "kraftpris.png", ref_month),
        _notat(df, target / "notat.md", ref_month),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
