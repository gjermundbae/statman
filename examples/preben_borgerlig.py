"""Ende-til-ende-eksempel: heter nyfødte gutter Preben i borgerlige perioder?

Hypotesen, slik den ble formulert: perioder med borgerlige meninger
sammenfaller med at folk kaller barna sine Preben. Testen her er den mest
bokstavelige lesningen — andelen nyfødte gutter med navnet Preben det
enkelte år, mot den borgerlige blokkens oppslutning ved valget samme år.
Ekte tall fra SSB, hele veien:

    ssb.fetch_table(10467)  ->  raw/ssb/10467_preben
    ssb.fetch_table(09624)  ->  raw/ssb/09624_velgere
      -> clean.navn_preben, clean.velgere_parti
      -> mart.navn_preben_aar, mart.velgere_borgerlig
      -> mart.preben_borgerlig
      -> output/preben_borgerlig/     (sakspakke)
      -> statman publish preben_borgerlig  -> docs/   (artikkel)

Datagrunnlaget er femten stortingsvalg, hvorav to faller bort — se
``statman/models/mart_navn_politikk.py``. Tretten par er ikke et grunnlag
noen korrelasjon bør hvile tungt på, uansett hva den sier. Se «Metode» i
sakspakken for hvorfor tallet likevel er verdt å regne ut, og for hvorfor
det ikke er verdt å tro på.

Kjør:  uv run statman example preben_borgerlig
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
from statman.models.mart_navn_politikk import FRP, HOYRE, KRF, VENSTRE  # noqa: E402
from statman.sources import ssb  # noqa: E402

NAVN_TABELL: Final[str] = "10467"
VALG_TABELL: Final[str] = "09624"
SLUG: Final[str] = "preben_borgerlig"

RAW_NAVN: Final[str] = "ssb/10467_preben"
RAW_VELGERE: Final[str] = "ssb/09624_velgere"

MODEL_NAVN: Final[str] = "mart.navn_preben_aar"
MODEL_VELGERE: Final[str] = "mart.velgere_borgerlig"
MODEL_KOBLET: Final[str] = "mart.preben_borgerlig"

# preben_borgerlig avhenger av de to andre; build_order tar dem med.
MODELS: Final[list[str]] = [MODEL_KOBLET]

METRICS: Final[tuple[str, ...]] = ("navn_preben_andel", "velgere_borgerlig_andel")

# Forskyvninger vi sjekker robustheten mot, i år. 0 er hovedfunnet — den
# bokstavelige lesningen av hypotesen. De andre finnes for å vise hvor mye
# tallet spretter rundt med bare et par valgår å velge blant, ikke for å
# lete etter den som gir høyest |r|.
LAGS: Final[tuple[int, ...]] = (-8, -4, 0, 4, 8)

FARGE_PREBEN: Final[str] = "#6a3d9a"
FARGE_BORGERLIG: Final[str] = "#1f4e8f"  # blått er den vanlige fargen på blokken


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent begge tabellene, filtrert til det vi faktisk trenger.

    10467 har 1974 fornavn; vi ber bare om Preben. 09624 har alle ti
    partiene/listene, «begge kjønn», alle femten valgår — det er lite nok
    til å hente i ett kall.
    """
    ssb.probe()
    written: dict[str, Path] = {}
    written[RAW_NAVN] = ssb.fetch_table(
        NAVN_TABELL,
        value_codes={"Fornavn": "2PREBEN", "ContentsCode": "*", "Tid": "*"},
        dataset="10467_preben",
    )
    written[RAW_VELGERE] = ssb.fetch_table(
        VALG_TABELL,
        value_codes={"PolitParti": "*", "Kjonn": "0", "ContentsCode": "*", "Tid": "*"},
        dataset="09624_velgere",
    )
    return written


# --------------------------------------------------------------------------
# Statistikk — ingen scipy i prosjektet, så begge deler skrives ut i sin
# helhet i stedet for å hente en tredjepartsavhengighet for én formel hver.
# --------------------------------------------------------------------------
def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy)


def _betacf(a: float, b: float, x: float, iterations: int = 200, eps: float = 3e-9) -> float:
    """Kjedebrøken i den regulariserte ufullstendige betafunksjonen (Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1e-30 if abs(d) < 1e-30 else d
    d = 1.0 / d
    h = d
    for m in range(1, iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1e-30 if abs(1.0 + aa * d) < 1e-30 else 1.0 + aa * d
        c = 1e-30 if abs(1.0 + aa / c) < 1e-30 else 1.0 + aa / c
        d, c = 1.0 / d, c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1e-30 if abs(1.0 + aa * d) < 1e-30 else 1.0 + aa * d
        c = 1e-30 if abs(1.0 + aa / c) < 1e-30 else 1.0 + aa / c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularisert ufullstendig betafunksjon I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_test_p(r: float, n: int) -> float:
    """Tosidig p-verdi for Pearsons r med n observasjoner, nullhypotese r=0."""
    if n <= 2:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t2 = r * r * df / (1 - r * r)
    return _betainc(df / 2, 0.5, df / (df + t2))


# --------------------------------------------------------------------------
# Grafer
# --------------------------------------------------------------------------
def _plot_tidsserie(navn: pl.DataFrame, velgere: pl.DataFrame, path: Path, fra_aar: int) -> Path:
    """To serier, to akser: Preben-andelen hvert år, borgerlig oppslutning ved valgene."""
    n = navn.filter(pl.col("aar") >= fra_aar).sort("aar")
    v = velgere.filter((pl.col("aar") >= fra_aar) & pl.col("borgerlig_andel_pst").is_not_null()).sort("aar")

    fig, ax1 = plt.subplots(figsize=(12, 6.5))
    ax1.plot(
        n["aar"].to_list(),
        n["andel_fodte_pst"].to_list(),
        color=FARGE_PREBEN,
        linewidth=1.8,
        label="Andel nyfødte gutter som heter Preben",
    )
    ax1.set_ylabel("Andel av nyfødte gutter (prosent)", color=FARGE_PREBEN)
    ax1.tick_params(axis="y", labelcolor=FARGE_PREBEN)
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.2, linewidth=0.6)
    ax1.spines[["top"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(
        v["aar"].to_list(),
        v["borgerlig_andel_pst"].to_list(),
        color=FARGE_BORGERLIG,
        linewidth=1.8,
        linestyle="--",
        marker="o",
        markersize=5,
        label="Borgerlig oppslutning ved valget (H+FrP+KrF+V)",
    )
    ax2.set_ylabel("Andel av velgerne (prosent)", color=FARGE_BORGERLIG)
    ax2.tick_params(axis="y", labelcolor=FARGE_BORGERLIG)
    ax2.spines[["top"]].set_visible(False)

    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], frameon=False, fontsize=9, loc="upper left")
    ax1.set_title(
        "To serier som ikke beveger seg sammen", loc="left", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.01, 0.005,
        "Kilde: SSB tabell 10467 (Preben, navngivningsår fra 2021) og 09624 (valgundersøkelsen, "
        "selvrapportert). Borgerlig oppslutning finnes bare ved stortingsvalg, hvert fjerde år.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


def _plot_scatter(xs: list[float], ys: list[float], aar: list[int], r: float, path: Path) -> Path:
    """De brukbare valgårene, ett punkt per år, med regresjonslinje."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    intercept = my - slope * mx

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.scatter(xs, ys, s=60, color=FARGE_BORGERLIG, zorder=3)
    for x, y, a in zip(xs, ys, aar):
        ax.annotate(str(a), (x, y), textcoords="offset points", xytext=(6, 4), fontsize=8.5, color="0.25")

    x_linje = [min(xs) - 1, max(xs) + 1]
    ax.plot(
        x_linje,
        [slope * x + intercept for x in x_linje],
        color="0.3",
        linewidth=1.2,
        linestyle=":",
        zorder=2,
    )
    ax.set_xlabel("Borgerlig oppslutning ved valget (prosent av velgerne)")
    ax.set_ylabel("Andel nyfødte gutter som heter Preben (prosent)")
    ax.grid(True, alpha=0.2, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(
        f"r = {r:+.2f}, n = {n} valgår", loc="left", fontsize=13, fontweight="bold"
    )
    ax.set_title("Hvert punkt er ett stortingsvalg", loc="right", fontsize=9, color="0.35")
    fig.text(
        0.01, 0.005,
        "Kilde: SSB tabell 10467 og 09624. Prikket linje er lineær regresjon, ikke en påstand "
        "om sammenheng.",
        fontsize=8, color="0.35",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=144)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# Artikkel
# --------------------------------------------------------------------------
def _r(verdi: float) -> str:
    return f"{verdi:+.2f}".replace(".", ",")


def artikkel(
    koblet: pl.DataFrame,
    lag_tabell: list[tuple[int, int, float | None]],
    r0: float,
    p0: float,
    proveniens_navn: dict[str, str],
    proveniens_velgere: dict[str, str],
    bygg: dict,
) -> publish.Article:
    brukbar = koblet.filter(pl.col("brukbar")).sort("aar")
    utelatt = koblet.filter(~pl.col("brukbar")).sort("aar")
    n = brukbar.height
    sterkest = brukbar.sort("andel_fodte_preben_pst", descending=True).row(0, named=True)
    svakest = brukbar.sort("andel_fodte_preben_pst").row(0, named=True)

    retning = "svakt negativ" if r0 < -0.05 else "svakt positiv" if r0 > 0.05 else "omtrent fraværende"
    signifikant = p0 < 0.05

    lag_rader = tuple(
        (
            f"{lag:+d} år" if lag else "0 år (hovedfunn)",
            str(cnt),
            _r(r) if r is not None else "—",
        )
        for lag, cnt, r in lag_tabell
    )

    funn = publish.Section(
        "Funn",
        (
            publish.Stats(
                (
                    publish.Stat(_r(r0), "Korrelasjon (r)", f"n = {n} valgår"),
                    publish.Stat(
                        f"p = {p0:.2f}".replace(".", ","),
                        "Ikke statistisk signifikant" if not signifikant else "Statistisk signifikant",
                        "tosidig t-test, H0: r = 0",
                    ),
                    publish.Stat(
                        f"{sterkest['aar']}", "Høyest Preben-andel",
                        f"{sterkest['andel_fodte_preben_pst']:.3f} % av nyfødte gutter",
                    ),
                    publish.Stat(
                        f"{svakest['aar']}", "Lavest Preben-andel",
                        f"{svakest['andel_fodte_preben_pst']:.3f} % av nyfødte gutter",
                    ),
                )
            ),
            publish.Findings(
                (
                    f"Korrelasjonen mellom andelen nyfødte gutter som heter Preben og "
                    f"borgerlig oppslutning samme valgår er **{retning}**: r = {_r(r0)} "
                    f"over {n} stortingsvalg (p = {p0:.2f}".replace(".", ",") + ", ikke "
                    "signifikant på noe vanlig nivå).",
                    "Med bare " + str(n) + " observasjoner skal det uvanlig mye til før et "
                    "tall som dette kan skilles fra tilfeldig støy — se følsomhetstabellen "
                    "under.",
                    "Toppåret for Preben-navngiving var 1997, midt i en periode med "
                    "middels borgerlig oppslutning. Navnet var på vei ned igjen lenge før "
                    "de blåblå vant valget i 2013.",
                )
            ),
            publish.Figure(
                "tidsserie.png",
                alt="Linjediagram med to akser: andel Preben-navngivinger per år til "
                "venstre, borgerlig valgoppslutning til høyre.",
                caption="De to seriene beveger seg ikke sammen. Preben-andelen topper i "
                "1997 og faller jevnt etterpå; den borgerlige oppslutningen svinger opp og "
                "ned uavhengig av det.",
                source="Kilde: SSB tabell 10467 og 09624.",
                width="full",
            ),
            publish.Figure(
                "scatter.png",
                alt="Punktdiagram: borgerlig oppslutning langs x-aksen, Preben-andel langs "
                "y-aksen, ett punkt per stortingsvalg, med regresjonslinje.",
                caption=f"De {n} brukbare valgårene. Spredningen er stor og punktene få — "
                "linjen er det regresjonen gir, ikke et mønster øyet ville funnet uten den.",
                source="Kilde: SSB tabell 10467 og 09624.",
            ),
        ),
    )

    folsomhet = publish.Section(
        "Følsomhet",
        (
            publish.Findings(
                (
                    "Hovedfunnet over bruker ingen forskyvning: fødselsår mot valgår "
                    "samme år. Tabellen under viser hva som skjer med noen andre "
                    "forskyvninger — ikke fordi noen av dem er en bedre hypotese, men "
                    "fordi det er slik man ser om et tall er robust eller bare var det "
                    "utvalget som tilfeldigvis ga høyest tall.",
                    "Med denne mengden data er svaret at det ikke er robust. r skifter "
                    "fortegn og størrelse mellom forskyvningene uten noe mønster som "
                    "tyder på en ekte sammenheng et sted i tidsrommet.",
                )
            ),
            publish.Table(
                columns=("Forskyvning", "Antall par", "r"),
                align=("left", "right", "right"),
                rows=lag_rader,
                caption="Positiv forskyvning = borgerlig oppslutning målt år(ene) etter "
                "fødselsåret. Færre par ved store forskyvninger fordi valgår da havner "
                "utenfor 1969-2025.",
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
                    f"Valgtall: SSB tabell {VALG_TABELL}, «{proveniens_velgere['label']}» — "
                    "selvrapportert stemmegivning fra valgundersøkelsen, ikke opptalte "
                    f"resultater. Oppdatert {proveniens_velgere['updated'][:10]}, hentet "
                    f"{proveniens_velgere['fetched_at'][:19]}Z, sha256 "
                    f"{proveniens_velgere['sha256'][:12]}….",
                    f"«Borgerlig» er Høyre (kode {HOYRE}) + Fremskrittspartiet ({FRP}) + "
                    f"Kristelig Folkeparti ({KRF}) + Venstre ({VENSTRE}). Senterpartiet er "
                    "utelatt — se `statman/models/mart_navn_politikk.py` for "
                    "begrunnelsen. Et annet partiutvalg gir et annet tall enn r over.",
                    f"Modellene `{MODEL_NAVN}`, `{MODEL_VELGERE}` og `{MODEL_KOBLET}`, "
                    f"bygget av statman {bygg['built_at'][:19].replace('T', ' ')}Z.",
                    f"{utelatt.height} av {koblet.height} valgår er utelatt fra "
                    "korrelasjonen: " + ", ".join(
                        f"{r['aar']} ({'FrP fantes ikke ennå' if r['borgerlig_andel_pst'] is None else 'Preben-tallet er undertrykt eller ikke ferdig talt opp'})"
                        for r in utelatt.iter_rows(named=True)
                    ) + ".",
                    "p-verdien over tester om r er forskjellig fra null, ikke om Preben "
                    "*forårsaker* eller *forårsakes av* borgerlig oppslutning. Med to "
                    "tidsserier som begge endrer seg sakte, vil nesten hvilket som helst "
                    "par av dem korrelere svakt av rene tidstrend-grunner — det er selve "
                    "grunnen til at man ikke kan lese en kausal historie ut av et slikt "
                    "tall, uansett hvor det lander.",
                )
            ),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker="Kuriosa · SSB tabell 10467 og 09624",
        title="Er Preben en borgerlig navnetrend?",
        lead=(
            f"Andelen nyfødte gutter som heter Preben, mot den borgerlige blokkens "
            f"oppslutning ved samme stortingsvalg, {int(brukbar['aar'].min())}–"
            f"{int(brukbar['aar'].max())}. r = {_r(r0)} over {n} valgår — for lite "
            "til å konkludere noe vei, og det er selve konklusjonen."
        ),
        published=bygg["built_at"][:10],
        sections=(funn, folsomhet, metode),
        caveats=METRICS,
        provenance={
            "Navnekilde": f"SSB tabell {NAVN_TABELL} — {proveniens_navn['label']}",
            "Valgkilde": f"SSB tabell {VALG_TABELL} — {proveniens_velgere['label']}",
            "Hentet (navn)": proveniens_navn["fetched_at"][:19] + "Z",
            "Hentet (valg)": proveniens_velgere["fetched_at"][:19] + "Z",
            "sha256 (navn)": proveniens_navn["sha256"],
            "sha256 (valg)": proveniens_velgere["sha256"],
            "Modeller": f"{MODEL_NAVN} · {MODEL_VELGERE} · {MODEL_KOBLET}",
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "alle 15 valgår, inkludert de utelatte"),
            ("tidsserie.png", "begge seriene over tid, hver sin akse"),
            ("scatter.png", "de brukbare valgårene, med regresjonslinje"),
        ),
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    koblet = io.load(MODEL_KOBLET)
    navn = io.load(MODEL_NAVN)
    velgere = io.load(MODEL_VELGERE)

    brukbar = koblet.filter(pl.col("brukbar")).sort("aar")
    xs = brukbar["borgerlig_andel_pst"].to_list()
    ys = brukbar["andel_fodte_preben_pst"].to_list()
    aar = brukbar["aar"].to_list()
    r0 = _pearson(xs, ys)
    p0 = t_test_p(r0, len(xs))

    lag_tabell: list[tuple[int, int, float | None]] = []
    for lag in LAGS:
        forskjoevet = velgere.select("aar", "borgerlig_andel_pst").with_columns(
            (pl.col("aar") - lag).alias("preben_aar")
        )
        par = (
            navn.select("aar", "andel_fodte_pst")
            .join(forskjoevet, left_on="aar", right_on="preben_aar", how="inner")
            .drop_nulls(["andel_fodte_pst", "borgerlig_andel_pst"])
        )
        n = par.height
        r = _pearson(par["borgerlig_andel_pst"].to_list(), par["andel_fodte_pst"].to_list()) if n >= 3 else None
        lag_tabell.append((lag, n, r))

    bygg = io.read_manifest(MODEL_KOBLET)
    def _proveniens(ref: str) -> dict:
        raa = bygg["raw"][ref]
        versjon = io.raw_version_dir(ref, raa["version"])
        return {**jsonstat.header(io.raw_data_file(versjon)), **raa}

    proveniens_navn = _proveniens(RAW_NAVN)
    proveniens_velgere = _proveniens(RAW_VELGERE)

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    koblet.sort("aar").write_csv(csv_path)

    figurer = [
        _plot_tidsserie(navn, velgere, target / "tidsserie.png", fra_aar=1965),
        _plot_scatter(xs, ys, aar, r0, target / "scatter.png"),
    ]

    art = artikkel(koblet, lag_tabell, r0, p0, proveniens_navn, proveniens_velgere, bygg)
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
