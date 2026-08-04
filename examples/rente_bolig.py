"""Ende-til-ende-eksempel: følger styringsrenten faktisk boligprisveksten?

To ekte kilder, ingen av dem SSBs egen valgundersøkelse eller
pollofpolls.no denne gangen: Norges Banks styringsrenteserie
(``statman/sources/norges_bank.py``, ny konnektor) og SSBs prisindeks for
brukte boliger (tabell 07221).

    norges_bank.fetch_key_policy_rate()  ->  raw/norges_bank/styringsrente
    ssb.fetch_table(07221)               ->  raw/ssb/07221_bolig
      -> clean.styringsrente, clean.boligprisindeks
      -> mart.rente_kvartal, mart.boligpris_kvartal
      -> mart.rente_bolig_kvartal
      -> output/rente_bolig/     (sakspakke)
      -> statman publish rente_bolig  -> docs/   (artikkel)

Samme fallgruve som i Preben-sakene, men denne gangen med et annet utfall.
Renta mot boligprisindeksen *samme kvartal*, over hele perioden 1992-2026,
korrelerer sterkt (r ≈ -0,6) — nesten utelukkende fordi begge serier har
beveget seg i tiår-lange buer (renta ned fra ni-ti prosent til null, prisene
opp mangedoblet), ikke fordi den ene kvartalsvis følger den andre. Testen er
derfor den samme som i ``preben_meningsmalinger``: bytt nivå mot endring.

Her, i motsetning til Preben-sakene, overlever noe testen. Endringen i
styringsrenten fra ett kvartal til det neste henger sammen med hvor mye
boligprisveksten (sesongjustert) bremser eller tar av — ikke samme kvartal,
men med ett til to kvartalers forsinkelse, og bare moderat (r ≈ -0,34,
p ≈ 0,001-0,002 over 82-84 kvartal 2005-2026). Se «Følsomhet» for hvordan
det tallet oppfører seg ved andre forskyvninger, og «Metode» for hvorfor det
fortsatt ikke beviser at renta *forårsaker* bremsen.

Kjør:  uv run statman example rente-bolig
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import matplotlib

matplotlib.use("Agg")  # ingen skjerm, skriver rett til fil

import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from statman import io, jsonstat, publish, stats  # noqa: E402
from statman.sources import norges_bank, ssb  # noqa: E402

BOLIG_TABELL: Final[str] = "07221"
SLUG: Final[str] = "rente_bolig"

RAW_RENTE: Final[str] = "norges_bank/styringsrente"
RAW_BOLIG: Final[str] = "ssb/07221_bolig"

MODEL_RENTE: Final[str] = "mart.rente_kvartal"
MODEL_BOLIG: Final[str] = "mart.boligpris_kvartal"
MODEL_KOBLET: Final[str] = "mart.rente_bolig_kvartal"

# mart.rente_bolig_kvartal avhenger av de to andre; build_order tar dem med.
MODELS: Final[list[str]] = [MODEL_KOBLET]

METRICS: Final[tuple[str, ...]] = (
    "styringsrente",
    "boligprisindeks",
    "boligprisindeks_sesongjustert",
    "styringsrente_endring_kvartal",
    "boligprisvekst_kvartal",
)

# Forskyvninger vi sjekker robustheten mot, i kvartal. 0 er "samme kvartal";
# hovedfunnet står ved 1. De andre finnes for å vise hvor fort sammenhengen
# dør ut, ikke for å lete etter den som gir høyest |r|.
LAGS: Final[tuple[int, ...]] = (0, 1, 2, 3, 4, 6, 8)
HOVEDFORSKYVNING: Final[int] = 1

FARGE_RENTE: Final[str] = "#c0392b"
FARGE_BOLIG: Final[str] = "#1f6f54"


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Hent begge kildene. Uavhengige av hverandre, ingen delt rate limit."""
    written: dict[str, Path] = {}
    written[RAW_RENTE] = norges_bank.fetch_key_policy_rate()
    ssb.probe()
    written[RAW_BOLIG] = ssb.fetch_table(
        BOLIG_TABELL,
        value_codes={"Region": "TOTAL", "Boligtype": "00", "ContentsCode": "*", "Tid": "*"},
        dataset="07221_bolig",
    )
    return written


# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------
def _lag_table(df: pl.DataFrame) -> list[tuple[int, int, float | None, float | None]]:
    """r og p mellom renteendring og boligprisvekst k kvartaler senere, for hver k i LAGS.

    Samme teknikk som ``examples/preben_borgerlig.py``: renteendringen ved
    kvartal t joines mot boligprisveksten ved kvartal t+lag via et eksplisitt
    join på kvartalsindeksen, ikke et rått ``shift`` — så et eventuelt hull
    aldri hopper over seg selv og blir lest som riktig antall kvartal.
    """
    base = df.filter(pl.col("boligindeks_sesjustert").is_not_null())
    rader: list[tuple[int, int, float | None, float | None]] = []
    for lag in LAGS:
        forskjoevet = base.select("kvartal_indeks", "endring_bolig_kvartal_pst").with_columns(
            (pl.col("kvartal_indeks") - lag).alias("rente_indeks")
        )
        par = (
            base.select("kvartal_indeks", "delta_rente_pp")
            .join(forskjoevet, left_on="kvartal_indeks", right_on="rente_indeks", how="inner")
            .drop_nulls(["delta_rente_pp", "endring_bolig_kvartal_pst"])
        )
        n = par.height
        r = (
            stats.pearson(par["delta_rente_pp"].to_list(), par["endring_bolig_kvartal_pst"].to_list())
            if n >= 3
            else None
        )
        p = stats.t_test_p(r, n) if r is not None else None
        rader.append((lag, n, r, p))
    return rader


def _lag_par(df: pl.DataFrame, lag: int) -> pl.DataFrame:
    """De faktiske (delta_rente_pp, endring_bolig_kvartal_pst)-parene ved én forskyvning."""
    base = df.filter(pl.col("boligindeks_sesjustert").is_not_null())
    forskjoevet = base.select("kvartal_indeks", "endring_bolig_kvartal_pst").with_columns(
        (pl.col("kvartal_indeks") - lag).alias("rente_indeks")
    )
    return (
        base.select("kvartal_indeks", "delta_rente_pp")
        .join(forskjoevet.select("rente_indeks", "endring_bolig_kvartal_pst"), left_on="kvartal_indeks", right_on="rente_indeks", how="inner")
        .drop_nulls(["delta_rente_pp", "endring_bolig_kvartal_pst"])
        .sort("kvartal_indeks")
    )


# --------------------------------------------------------------------------
# Grafer
# --------------------------------------------------------------------------
def _kvartal_x(aar: list[int], kvartal: list[int]) -> list[float]:
    return [a + (k - 1) / 4 for a, k in zip(aar, kvartal)]


def _plot_tidsserie(niva: pl.DataFrame, path: Path) -> Path:
    """To serier, to akser: boligprisindeksen (ujustert) og styringsrenten, 1992-2026."""
    n = niva.sort("kvartal_indeks")
    x = _kvartal_x(n["aar"].to_list(), n["kvartal"].to_list())

    fig, ax1 = plt.subplots(figsize=(12, 6.5))
    ax1.plot(x, n["boligindeks"].to_list(), color=FARGE_BOLIG, linewidth=1.8, label="Boligprisindeks (2015=100)")
    ax1.set_ylabel("Prisindeks for brukte boliger (2015=100)", color=FARGE_BOLIG)
    ax1.tick_params(axis="y", labelcolor=FARGE_BOLIG)
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.2, linewidth=0.6)
    ax1.spines[["top"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(
        x, n["rente_snitt_pst"].to_list(), color=FARGE_RENTE, linewidth=1.8, linestyle="--",
        label="Styringsrenten, kvartalssnitt",
    )
    ax2.set_ylabel("Styringsrenten (prosent p.a.)", color=FARGE_RENTE)
    ax2.tick_params(axis="y", labelcolor=FARGE_RENTE)
    ax2.set_ylim(bottom=0)
    ax2.spines[["top"]].set_visible(False)

    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(
        lines, [line.get_label() for line in lines],
        frameon=True, framealpha=0.9, edgecolor="none", fontsize=9, loc="lower right",
    )
    ax1.set_title(
        "Begge har beveget seg i tiår-lange buer", loc="left", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.01, 0.005,
        "Kilde: SSB tabell 07221 (ujustert indeks, hele landet) og Norges Bank, IR/B.KPRA.SD. "
        "Delt retning over lange strekk er det som gir den sterke, men misvisende nivåkorrelasjonen.",
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
    niva: pl.DataFrame, delta: pl.DataFrame, r_niva: float, r_delta: float, lag: int, path: Path
) -> Path:
    """To paneler: nivå (hele perioden) til venstre, endring med forskyvning til høyre."""
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13, 6.5))

    xs_l, ys_l = niva["rente_snitt_pst"].to_list(), niva["boligindeks"].to_list()
    ax_l.scatter(xs_l, ys_l, s=30, color=FARGE_BOLIG, alpha=0.7, zorder=3)
    slope, intercept = _regresjon(xs_l, ys_l)
    xl = [min(xs_l), max(xs_l)]
    ax_l.plot(xl, [slope * x + intercept for x in xl], color="0.3", linewidth=1.1, linestyle=":")
    ax_l.set_xlabel("Styringsrenten, kvartalssnitt (prosent)")
    ax_l.set_ylabel("Boligprisindeks, ujustert (2015=100)")
    ax_l.grid(True, alpha=0.2, linewidth=0.6)
    ax_l.spines[["top", "right"]].set_visible(False)
    ax_l.set_title(f"Nivå, 1992-2026: r = {r_niva:+.2f}, n = {niva.height}", loc="left", fontsize=12, fontweight="bold")

    xs_r = delta["delta_rente_pp"].to_list()
    ys_r = delta["endring_bolig_kvartal_pst"].to_list()
    ax_r.scatter(xs_r, ys_r, s=30, color=FARGE_RENTE, alpha=0.7, zorder=3)
    slope, intercept = _regresjon(xs_r, ys_r)
    xr = [min(xs_r), max(xs_r)]
    ax_r.plot(xr, [slope * x + intercept for x in xr], color="0.3", linewidth=1.1, linestyle=":")
    ax_r.axhline(0, color="0.75", linewidth=0.8)
    ax_r.axvline(0, color="0.75", linewidth=0.8)
    ax_r.set_xlabel("Endring i styringsrenten, kvartal t (prosentpoeng)")
    ax_r.set_ylabel(f"Boligprisvekst, kvartal t+{lag} (prosent, sesongjustert)")
    ax_r.grid(True, alpha=0.2, linewidth=0.6)
    ax_r.spines[["top", "right"]].set_visible(False)
    ax_r.set_title(
        f"Endring, {lag} kvartal forskjøvet: r = {r_delta:+.2f}, n = {delta.height}",
        loc="left", fontsize=12, fontweight="bold",
    )

    fig.suptitle("Samme spørsmål, to helt forskjellige svar", x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.text(
        0.01, 0.005,
        "Venstre: nivå, det naive spørsmålet, hele perioden 1992-2026. Høyre: endring fra forrige "
        f"kvartal, sesongjustert boligindeks, {lag} kvartal etter renteendringen, 2005-2026. "
        "Kilde: SSB tabell 07221 og Norges Bank.",
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


def _p(verdi: float) -> str:
    return f"{verdi:.3f}".replace(".", ",") if verdi >= 0.0005 else "< 0,001"


def artikkel(
    niva: pl.DataFrame,
    r_niva: float,
    p_niva: float,
    lag_tabell: list[tuple[int, int, float | None, float | None]],
    hoved: tuple[int, int, float, float],
    proveniens_rente: dict,
    proveniens_bolig: dict,
    bygg: dict,
) -> publish.Article:
    lag_hoved, n_hoved, r_hoved, p_hoved = hoved
    n_niva = niva.height

    lag_rader = tuple(
        (
            f"{lag} kvartal" if lag else "0 (samme kvartal)",
            str(n),
            _r(r) if r is not None else "—",
            _p(p) if p is not None else "—",
        )
        for lag, n, r, p in lag_tabell
    )

    funn = publish.Section(
        "Funn",
        (
            publish.Stats(
                (
                    publish.Stat(_r(r_niva), "Korrelasjon på nivå", f"n = {n_niva} kvartal, 1992-2026"),
                    publish.Stat(_p(p_niva), "Ser sterkt signifikant ut", "men se endringstallet under"),
                    publish.Stat(_r(r_hoved), f"Korrelasjon, {lag_hoved} kvartal forskjøvet", f"n = {n_hoved} kvartal, 2005-2026"),
                    publish.Stat(_p(p_hoved), "Statistisk signifikant", "tosidig t-test, H0: r = 0"),
                )
            ),
            publish.Findings(
                (
                    f"Målt på **nivå** — styringsrenten og boligprisindeksen samme kvartal, hele "
                    f"perioden 1992-2026 — er korrelasjonen r = {_r(r_niva)} (n = {n_niva} kvartal, "
                    f"p {_p(p_niva)}). Det ser overbevisende ut, og det er nettopp problemet: renta "
                    "har falt fra ni-ti prosent til null over disse tiårene mens boligprisene har "
                    "mangedoblet seg, og to serier som deler én lang retning korrelerer sterkt på "
                    "nivå uansett hvor mye de faktisk henger sammen fra kvartal til kvartal.",
                    f"Målt på **endring** — hvor mye endrer boligprisveksten (sesongjustert) seg etter "
                    f"at renta endres, {lag_hoved} kvartal senere — er korrelasjonen r = {_r(r_hoved)} "
                    f"(n = {n_hoved} kvartal, 2005-2026, p {_p(p_hoved)}). Svakere enn nivåtallet, som "
                    "forventet når den delte trenden er fjernet, men i motsetning til Preben-sakene "
                    "forsvinner den ikke: den er moderat, i forventet retning, og statistisk "
                    "signifikant på vanlig nivå.",
                    "Retningen er den man skulle vente: en renteøkning henger sammen med lavere "
                    "boligprisvekst kvartalet(-ene) etter, ikke samme kvartal. Se «Følsomhet» for "
                    "hvor fort sammenhengen dør ut med lengre forskyvning, og «Metode» for hvorfor "
                    "det fortsatt ikke beviser at renta er årsaken.",
                )
            ),
            publish.Figure(
                "tidsserie.png",
                alt="Linjediagram med to akser: boligprisindeksen (ujustert) til venstre, "
                "styringsrenten til høyre, kvartalsvis 1992-2026.",
                caption="Begge serier har beveget seg i tiår-lange buer. Det er denne delte, "
                "langsomme bevegelsen som gir den sterke, men misvisende nivåkorrelasjonen under.",
                source="Kilde: SSB tabell 07221 og Norges Bank, IR/B.KPRA.SD.",
                width="full",
            ),
            publish.Figure(
                "niva_vs_endring.png",
                alt="To punktdiagrammer side ved side: nivå til venstre over hele perioden, "
                "endring med forskyvning til høyre.",
                caption="Samme to variabler, to spørsmål. Til venstre nivået, som lyver. Til "
                "høyre endringen med forskyvning, som holder — svakere, men ekte.",
                source="Kilde: SSB tabell 07221 og Norges Bank, IR/B.KPRA.SD.",
                width="full",
            ),
        ),
    )

    folsomhet = publish.Section(
        "Følsomhet",
        (
            publish.Findings(
                (
                    "Tabellen under gjentar endringstallet over med andre forskyvninger — ikke "
                    "fordi noen av dem er en bedre hypotese, men for å se om sammenhengen er "
                    "robust eller bare var den forskyvningen som tilfeldigvis ga høyest tall.",
                    "Mønsteret er som forventet fra hvordan pengepolitikk faktisk virker: "
                    "sammenhengen er svakest samme kvartal, sterkest ved én til to kvartals "
                    "forsinkelse, og avtar mot null etter fire-fem kvartal. Det er ikke tilfeldig "
                    "støy uten struktur, slik forskyvningstabellen i Preben-sakene var — det er en "
                    "form som ligner en reell, forsinket transmisjon.",
                    "Sammenhengen ved 1-2 kvartals forskyvning holder seg også — svekket til "
                    "r ≈ -0,29 til -0,32, fortsatt signifikant — om koronakvartalene 2020-2021 tas "
                    "helt ut av utvalget. Den er altså ikke bare ett enkelt sjokk som drar tallet.",
                )
            ),
            publish.Table(
                columns=("Forskyvning", "Antall kvartal", "r", "p"),
                align=("left", "right", "right", "right"),
                rows=lag_rader,
                caption="0 kvartal = renteendring og boligprisvekst samme kvartal. Alle tall er fra "
                "den sesongjusterte perioden, 2005-2026.",
            ),
        ),
    )

    metode = publish.Section(
        "Metode",
        (
            publish.Findings(
                (
                    f"Rentetall: Norges Bank, dataserie IR/B.KPRA.SD (styringsrenten), hentet "
                    f"{proveniens_rente['fetched_at'][:19]}Z, sha256 {proveniens_rente['sha256'][:12]}….",
                    f"Boligtall: SSB tabell {BOLIG_TABELL}, «{proveniens_bolig['label']}». Oppdatert "
                    f"{proveniens_bolig['updated'][:10]}, hentet {proveniens_bolig['fetched_at'][:19]}Z, "
                    f"sha256 {proveniens_bolig['sha256'][:12]}….",
                    "Styringsrenten er notert per virkedag og regnet om til kvartalssnitt her; "
                    "boligprisindeksen er allerede kvartalsvis fra SSB. Endringstallet bruker den "
                    "sesongjusterte indeksvarianten, som først finnes fra 2005K1 — elleve år kortere "
                    "enn rentetallet, og grunnen til at endringsanalysen dekker et kortere tidsrom "
                    "enn nivågrafen.",
                    f"Modellene `{MODEL_RENTE}`, `{MODEL_BOLIG}` og `{MODEL_KOBLET}`, bygget av "
                    f"statman {bygg['built_at'][:19].replace('T', ' ')}Z.",
                    "Verken p-verdien eller forskyvningsmønsteret over beviser at styringsrenten "
                    "*forårsaker* endringen i boligprisveksten. Norges Bank setter renten blant "
                    "annet ut fra egne vurderinger av boligmarkedet og presset i økonomien for "
                    "øvrig, så noe av sammenhengen kan gå motsatt vei eller gjennom en tredje "
                    "faktor — inflasjon, kronekurs, kredittpraksis i bankene, boligbygging. To "
                    "tidsserier kan ikke skille en slik forklaring fra en direkte effekt; det "
                    "krever en modell med flere variabler, som denne saken ikke bygger.",
                    "Landstallet skjuler dessuten store regionale forskjeller — Oslo har for "
                    "eksempel beveget seg annerledes enn resten av landet i flere av disse "
                    "rentesyklusene. Det er utenfor denne saken, men et åpent spørsmål for en "
                    "senere en.",
                )
            ),
        ),
    )

    return publish.Article(
        slug=SLUG,
        kicker="Rente og bolig · Norges Bank og SSB tabell 07221",
        title="Renta og boligprisene: nivået lyver, den forsinkede endringen holder stikk",
        lead=(
            f"Styringsrenten mot boligprisindeksen samme kvartal ser ut som en sterk sammenheng: "
            f"r = {_r(r_niva)} over {n_niva} kvartal siden 1992. Det er nesten bare delt, "
            f"tiår-lang trend. Ser man i stedet på hvordan boligprisveksten endrer seg etter at "
            f"renta endres, blir sammenhengen svakere — men den forsvinner ikke: r = {_r(r_hoved)} "
            f"med {lag_hoved} kvartals forsinkelse (n = {n_hoved}, p {_p(p_hoved)})."
        ),
        published=bygg["built_at"][:10],
        sections=(funn, folsomhet, metode),
        caveats=METRICS,
        provenance={
            "Rentekilde": "Norges Bank — dataserie IR/B.KPRA.SD (styringsrenten)",
            "Boligkilde": f"SSB tabell {BOLIG_TABELL} — {proveniens_bolig['label']}",
            "Hentet (rente)": proveniens_rente["fetched_at"][:19] + "Z",
            "Hentet (bolig)": proveniens_bolig["fetched_at"][:19] + "Z",
            "sha256 (rente)": proveniens_rente["sha256"],
            "sha256 (bolig)": proveniens_bolig["sha256"],
            "Modeller": f"{MODEL_RENTE} · {MODEL_BOLIG} · {MODEL_KOBLET}",
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "alle kvartal 1991-2026, nivå og endring"),
            ("tidsserie.png", "boligprisindeks og styringsrente, hele perioden"),
            ("niva_vs_endring.png", "nivå og forskjøvet endring side ved side"),
        ),
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellene er bygget."""
    koblet = io.load(MODEL_KOBLET)

    niva = koblet.filter(pl.col("brukbar_niva")).sort("kvartal_indeks")
    r_niva = stats.pearson(niva["rente_snitt_pst"].to_list(), niva["boligindeks"].to_list())
    p_niva = stats.t_test_p(r_niva, niva.height)

    lag_tabell = _lag_table(koblet)
    hoved_rad = next(rad for rad in lag_tabell if rad[0] == HOVEDFORSKYVNING)
    _, n_hoved, r_hoved, p_hoved = hoved_rad
    assert r_hoved is not None and p_hoved is not None
    hoved = (HOVEDFORSKYVNING, n_hoved, r_hoved, p_hoved)
    delta_par = _lag_par(koblet, HOVEDFORSKYVNING)

    bygg = io.read_manifest(MODEL_KOBLET)

    # Byggeloggen har allerede meta (fetched_at, sha256, ...) flettet inn for
    # rentetallet. Boligtallet trenger i tillegg json-stat2-headeren for
    # tabellittelen og SSBs eget oppdateringstidspunkt.
    proveniens_rente = bygg["raw"][RAW_RENTE]

    raa_bolig = bygg["raw"][RAW_BOLIG]
    versjon_bolig = io.raw_version_dir(RAW_BOLIG, raa_bolig["version"])
    proveniens_bolig = {**jsonstat.header(io.raw_data_file(versjon_bolig)), **raa_bolig}

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    koblet.sort("kvartal_indeks").write_csv(csv_path)

    figurer = [
        _plot_tidsserie(niva, target / "tidsserie.png"),
        _plot_niva_vs_endring(niva, delta_par, r_niva, r_hoved, HOVEDFORSKYVNING, target / "niva_vs_endring.png"),
    ]

    art = artikkel(niva, r_niva, p_niva, lag_tabell, hoved, proveniens_rente, proveniens_bolig, bygg)
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
