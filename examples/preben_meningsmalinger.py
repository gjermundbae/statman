"""Ende-til-ende-eksempel: samme spørsmål som preben_borgerlig, årlig i stedet
for hvert fjerde år — og på endring i stedet for nivå.

Den første saken (``examples/preben_borgerlig.py``) brukte ekte
valgresultater, men de finnes bare hvert fjerde år. Denne bruker
pollofpolls.no sitt månedlige snitt av meningsmålinger i stedet, som gir et
tall for *hvert* år 2008-2025 — atten i stedet for femten, og ingen
fireårige hull.

Det avslører en felle den forrige saken ikke kunne vise: målt på *nivå*
korrelerer Preben-andelen og den borgerlige oppslutningen ganske sterkt
(r ≈ 0,6) i dette tidsrommet. Det er ikke en oppdagelse. Begge seriene
gled nedover det meste av 2008-2020, og to serier som deler en retning vil
korrelere på nivå nesten uansett hva de faktisk måler. Saken regner derfor
også ut endringen fra år til år for begge serier — trend i stedet for nivå
— og der forsvinner sammenhengen nesten helt. Se «Funn» for tallene.

    ssb.fetch_table(10467)              ->  raw/ssb/10467_preben
    pollofpolls.fetch_stortinget_snitt  ->  raw/pollofpolls/stortinget_snitt
      -> clean.navn_preben, clean.meningsmaling_parti
      -> mart.navn_preben_aar, mart.meningsmaling_aar,
         mart.velgere_borgerlig_meningsmaling
      -> mart.preben_trend
      -> output/preben_meningsmalinger/     (sakspakke)
      -> statman publish preben_meningsmalinger  -> docs/   (artikkel)

Kjør:  uv run statman example preben-trend
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, jsonstat, publish, stats  # noqa: E402
from statman.models.clean_pollofpolls import RAW_SNITT  # noqa: E402
from statman.models.clean_ssb_navn import RAW_NAVN  # noqa: E402
from statman.models.mart_meningsmaling_politikk import FRP, HOYRE, KRF, VENSTRE  # noqa: E402
from statman.sources import pollofpolls, ssb  # noqa: E402

NAVN_TABELL: Final[str] = "10467"
SLUG: Final[str] = "preben_meningsmalinger"

MODEL_NAVN: Final[str] = "mart.navn_preben_aar"
MODEL_BORGERLIG: Final[str] = "mart.velgere_borgerlig_meningsmaling"
MODEL_TREND: Final[str] = "mart.preben_trend"

# preben_trend avhenger av de andre; build_order tar dem med.
MODELS: Final[list[str]] = [MODEL_TREND]

METRICS: Final[tuple[str, ...]] = (
    "navn_preben_andel",
    "meningsmaling_borgerlig_andel",
    "meningsmaling_borgerlig_endring",
    "navn_preben_endring",
)

FARGE_PREBEN: Final[str] = "#6a3d9a"
FARGE_BORGERLIG: Final[str] = "#1f4e8f"


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent begge kildene. Uavhengig av om preben_borgerlig har kjørt først."""
    ssb.probe()
    written: dict[str, Path] = {}
    written[RAW_NAVN] = ssb.fetch_table(
        NAVN_TABELL,
        value_codes={"Fornavn": "2PREBEN", "ContentsCode": "*", "Tid": "*"},
        dataset="10467_preben",
    )
    written[RAW_SNITT] = pollofpolls.fetch_stortinget_snitt()
    return written


# --------------------------------------------------------------------------
# Grafer
# --------------------------------------------------------------------------
def _plot_tidsserie(navn: pl.DataFrame, borgerlig: pl.DataFrame, path: Path) -> Path:
    n = navn.filter((pl.col("aar") >= 2008) & (pl.col("aar") <= 2025)).sort("aar")
    b = borgerlig.filter(
        (pl.col("aar") >= 2008) & (pl.col("aar") <= 2025) & pl.col("borgerlig_andel_pst").is_not_null()
    ).sort("aar")

    fig, ax1 = plt.subplots(figsize=(12, 6.5))
    ax1.plot(
        n["aar"].to_list(),
        n["andel_fodte_pst"].to_list(),
        color=FARGE_PREBEN,
        linewidth=1.8,
        marker="o",
        markersize=4,
        label="Andel nyfødte gutter som heter Preben",
    )
    ax1.set_ylabel("Andel av nyfødte gutter (prosent)", color=FARGE_PREBEN)
    ax1.tick_params(axis="y", labelcolor=FARGE_PREBEN)
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.2, linewidth=0.6)
    ax1.spines[["top"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(
        b["aar"].to_list(),
        b["borgerlig_andel_pst"].to_list(),
        color=FARGE_BORGERLIG,
        linewidth=1.8,
        linestyle="--",
        label="Borgerlig oppslutning, årssnitt av meningsmålinger",
    )
    ax2.set_ylabel("Andel av velgerne (prosent)", color=FARGE_BORGERLIG)
    ax2.tick_params(axis="y", labelcolor=FARGE_BORGERLIG)
    ax2.spines[["top"]].set_visible(False)

    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], frameon=False, fontsize=9, loc="upper right")
    ax1.set_title(
        "To serier som begge glir nedover — i lang tid", loc="left", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.01, 0.005,
        "Kilde: SSB tabell 10467 (hull = undertrykt eller ikke ferdig talt opp) og "
        "pollofpolls.no (årssnitt av månedlige meningsmålinger, hele landet).",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _regresjon(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return slope, my - slope * mx


def _plot_niva_vs_endring(
    niva: pl.DataFrame, delta: pl.DataFrame, r_niva: float, r_delta: float, path: Path
) -> Path:
    """To paneler, samme to variabler: nivå til venstre, endring år for år til høyre."""
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13, 6.5))

    paneler = (
        (ax_l, niva, "borgerlig_andel_pst", "andel_fodte_preben_pst", r_niva,
         "Nivå", "Borgerlig oppslutning (prosent)", "Preben-andel (prosent)"),
        (ax_r, delta, "delta_borgerlig_pst", "delta_andel_fodte_preben_pst", r_delta,
         "Endring fra året før", "Endring, borgerlig (prosentpoeng)", "Endring, Preben-andel (prosentpoeng)"),
    )
    for ax, df, xcol, ycol, r, tittel, xlabel, ylabel in paneler:
        xs, ys, aar = df[xcol].to_list(), df[ycol].to_list(), df["aar"].to_list()
        ax.scatter(xs, ys, s=55, color=FARGE_BORGERLIG, zorder=3)
        for x, y, a in zip(xs, ys, aar):
            ax.annotate(str(a), (x, y), textcoords="offset points", xytext=(6, 4), fontsize=8, color="0.25")
        slope, intercept = _regresjon(xs, ys)
        x_linje = [min(xs) - 0.5, max(xs) + 0.5]
        ax.plot(x_linje, [slope * x + intercept for x in x_linje], color="0.3", linewidth=1.1, linestyle=":")
        if tittel == "Nivå":
            ax.axhline(0, color="0.85", linewidth=0.8)
        else:
            ax.axhline(0, color="0.75", linewidth=0.8)
            ax.axvline(0, color="0.75", linewidth=0.8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.2, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_title(f"{tittel}: r = {r:+.2f}, n = {len(xs)}", loc="left", fontsize=12, fontweight="bold")

    fig.suptitle(
        "Samme to variabler, to helt forskjellige svar", x=0.01, ha="left", fontsize=15, fontweight="bold"
    )
    fig.text(
        0.01, 0.005,
        "Venstre: nivå, det naive spørsmålet. Høyre: endring fra året før, som fjerner den delte "
        "trenden. Kilde: SSB tabell 10467 og pollofpolls.no.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.93))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# Artikkel
# --------------------------------------------------------------------------
def _r(verdi: float) -> str:
    return f"{verdi:+.2f}".replace(".", ",")


def artikkel(
    niva: pl.DataFrame,
    delta: pl.DataFrame,
    r_niva: float,
    p_niva: float,
    r_delta: float,
    p_delta: float,
    proveniens_navn: dict,
    proveniens_snitt: dict,
    bygg: dict,
) -> publish.Article:
    n_niva, n_delta = niva.height, delta.height

    funn = publish.Section(
        "Funn",
        (
            publish.Stats(
                (
                    publish.Stat(_r(r_niva), "Korrelasjon på nivå", f"n = {n_niva} år"),
                    publish.Stat(
                        f"p = {p_niva:.2f}".replace(".", ","),
                        "Ser signifikant ut" if p_niva < 0.05 else "Ikke signifikant",
                        "men se endringstallet under",
                    ),
                    publish.Stat(_r(r_delta), "Korrelasjon på endring", f"n = {n_delta} år"),
                    publish.Stat(
                        f"p = {p_delta:.2f}".replace(".", ","),
                        "Ikke statistisk signifikant" if p_delta >= 0.05 else "Statistisk signifikant",
                        "tosidig t-test, H0: r = 0",
                    ),
                )
            ),
            publish.Findings(
                (
                    f"Målt på **nivå** — årets Preben-andel mot årets borgerlige "
                    f"meningsmålingssnitt — er korrelasjonen r = {_r(r_niva)} over "
                    f"{n_niva} år. Det ser ut som noe, og det er nettopp problemet: "
                    "begge seriene falt gjennom mesteparten av 2008-2020, og to serier "
                    "som deler en retning korrelerer på nivå uansett hva de faktisk "
                    "måler.",
                    f"Målt på **endring fra året før** — fjerner den delte trenden og "
                    "spør om svingningene følges at fra ett år til det neste — er "
                    f"korrelasjonen r = {_r(r_delta)} over {n_delta} år: "
                    f"{'fortsatt ikke null, men ' if abs(r_delta) > 0.3 else ''}"
                    "ikke noe som skiller seg fra tilfeldig støy. Det er trendtallet, "
                    "ikke nivåtallet, som svarer på om Preben-navngiving og borgerlig "
                    "stemning faktisk beveger seg sammen.",
                    "Konklusjonen er den samme som i den første saken om Preben og "
                    "borgerlig oppslutning, nå fra en annen kilde og en strengere "
                    "test: nei.",
                )
            ),
            publish.Figure(
                "tidsserie.png",
                alt="Linjediagram med to akser: Preben-andel per år til venstre, "
                "borgerlig meningsmålingssnitt til høyre, 2008-2025.",
                caption="Begge seriene faller gjennom mesteparten av perioden. Det er "
                "denne delte retningen som gir det misvisende sterke nivåtallet under.",
                source="Kilde: SSB tabell 10467 og pollofpolls.no.",
                width="full",
            ),
            publish.Figure(
                "niva_vs_endring.png",
                alt="To punktdiagrammer side ved side: nivå til venstre med tydelig "
                "positiv sammenheng, endring år for år til høyre med ingen tydelig "
                "sammenheng.",
                caption="Samme to variabler. Til venstre ser det ut som en sammenheng. "
                "Til høyre, etter at den delte trenden er fjernet, gjør det ikke det.",
                source="Kilde: SSB tabell 10467 og pollofpolls.no.",
                width="full",
            ),
        ),
    )

    metode = publish.Section(
        "Metode",
        (
            publish.Findings(
                (
                    f"Navnetall: SSB tabell {NAVN_TABELL}, «{proveniens_navn['label']}». "
                    f"Oppdatert {proveniens_navn['updated'][:10]}, hentet "
                    f"{proveniens_navn['fetched_at'][:19]}Z, sha256 "
                    f"{proveniens_navn['sha256'][:12]}….",
                    "Meningsmålingstall: pollofpolls.no, det redaksjonelt beregnede "
                    "snittet av nasjonale meningsmålinger — ikke et opptalt resultat. "
                    f"Hentet {proveniens_snitt['fetched_at'][:19]}Z, sha256 "
                    f"{proveniens_snitt['sha256'][:12]}….",
                    "Årssnittet er regnet ut her, ikke hentet ferdig: gjennomsnitt av "
                    "de tolv månedlige snittene i kalenderåret. «Borgerlig» er samme "
                    f"fire partier som i den første saken — {HOYRE} + {FRP} + {KRF} + "
                    f"{VENSTRE} — nå identifisert ved navn i pollofpolls.no sin CSV i "
                    "stedet for SSB-koder.",
                    "Endringstallene bruker bare par av *påfølgende* år med tall i "
                    "begge ender — et hull i Preben-serien hopper aldri over seg selv "
                    "og blir lest som ett års endring. Se "
                    "`statman/models/mart_meningsmaling_politikk.py` for logikken.",
                    f"Modellene `{MODEL_NAVN}`, `{MODEL_BORGERLIG}` og `{MODEL_TREND}`, "
                    f"bygget av statman {bygg['built_at'][:19].replace('T', ' ')}Z.",
                    "p-verdiene tester om r er forskjellig fra null, ikke om det ene "
                    "forårsaker det andre. Nivåtallet over er tatt med i sin helhet, "
                    "ikke luket bort, nettopp fordi det er et så godt eksempel på "
                    "hvorfor nivåkorrelasjon mellom to trendede tidsserier ikke beviser "
                    "noe — spuriøs korrelasjon er et kjent fenomen, ikke noe spesielt "
                    "ved Preben eller borgerlig politikk.",
                )
            ),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker="Kuriosa, del 2 · pollofpolls.no og SSB tabell 10467",
        title="Preben og meningsmålingene: nivå lurer deg, endring gjør ikke",
        lead=(
            f"Samme spørsmål som forrige gang, nå årlig i stedet for hvert fjerde år: "
            f"r = {_r(r_niva)} på nivå ({n_niva} år) ser ut som noe — helt til man "
            f"ser på endringen fra år til år i stedet, der det blir r = {_r(r_delta)} "
            f"({n_delta} år). Delt trend, ikke delt skjebne."
        ),
        published=bygg["built_at"][:10],
        sections=(funn, metode),
        caveats=METRICS,
        provenance={
            "Navnekilde": f"SSB tabell {NAVN_TABELL} — {proveniens_navn['label']}",
            "Meningsmålingskilde": "pollofpolls.no — «Gjennomsnitt av nasjonale meningsmålinger om stortingsvalg»",
            "Hentet (navn)": proveniens_navn["fetched_at"][:19] + "Z",
            "Hentet (meningsmålinger)": proveniens_snitt["fetched_at"][:19] + "Z",
            "sha256 (navn)": proveniens_navn["sha256"],
            "sha256 (meningsmålinger)": proveniens_snitt["sha256"],
            "Modeller": f"{MODEL_NAVN} · {MODEL_BORGERLIG} · {MODEL_TREND}",
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "alle år 2008-2026, nivå og endring, inkludert de ubrukelige"),
            ("tidsserie.png", "begge seriene over tid, hver sin akse"),
            ("niva_vs_endring.png", "nivå og endring side ved side"),
        ),
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    trend = io.load(MODEL_TREND)
    navn = io.load(MODEL_NAVN)
    borgerlig = io.load(MODEL_BORGERLIG)

    niva = trend.filter(pl.col("brukbar_niva")).sort("aar")
    delta = trend.filter(pl.col("brukbar_delta")).sort("aar")

    r_niva = stats.pearson(niva["borgerlig_andel_pst"].to_list(), niva["andel_fodte_preben_pst"].to_list())
    p_niva = stats.t_test_p(r_niva, niva.height)
    r_delta = stats.pearson(
        delta["delta_borgerlig_pst"].to_list(), delta["delta_andel_fodte_preben_pst"].to_list()
    )
    p_delta = stats.t_test_p(r_delta, delta.height)

    bygg = io.read_manifest(MODEL_TREND)

    def _proveniens(ref: str) -> dict:
        raa = bygg["raw"][ref]
        versjon = io.raw_version_dir(ref, raa["version"])
        meta = io.read_meta(versjon)
        return {**raa, "label": meta.get("endpoint", ref), "updated": meta.get("fetched_at", "")}

    # Navnetallet har en ekte json-stat2-header med tabellittel og
    # SSBs oppdateringstidspunkt; meningsmålingskilden er en CSV uten det,
    # så den nøyer seg med det byggeloggen og rå-kvitteringen faktisk har.
    raa_navn = bygg["raw"][RAW_NAVN]
    versjon_navn = io.raw_version_dir(RAW_NAVN, raa_navn["version"])
    proveniens_navn = {**jsonstat.header(io.raw_data_file(versjon_navn)), **raa_navn}
    proveniens_snitt = _proveniens(RAW_SNITT)

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    trend.sort("aar").write_csv(csv_path)

    figurer = [
        _plot_tidsserie(navn, borgerlig, target / "tidsserie.png"),
        _plot_niva_vs_endring(niva, delta, r_niva, r_delta, target / "niva_vs_endring.png"),
    ]

    art = artikkel(niva, delta, r_niva, p_niva, r_delta, p_delta, proveniens_navn, proveniens_snitt, bygg)
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
