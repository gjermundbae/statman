"""Ende-til-ende, satire: norske skatteutflyttere mot FIFA-rankingen.

    fifa.fetch()              -> raw/fifa/world_ranking_men
    utflyttere.ingest()       -> raw/utflyttere/roster
      -> clean.fifa_ranking, clean.utflyttere
      -> mart.utflyttere_fifa
      -> output/utflyttere_fifa/     (sakspakke)
      -> statman publish utflyttere_fifa  -> docs/   (artikkel)

Premisset: en utflytter får ikke lov til å heie på Norge lenger, bare på sitt
nye hjemland. Spørsmålet tabellen stiller er derfor ikke om utflyttingen var
lur — det sier den ingenting om — men rent og skjært om det nye hjemlandet
er bedre eller dårligere plassert på FIFA/Coca-Cola Men's World Ranking enn
Norge er. Se ``statman/models/mart_utflyttere_fifa.py`` for differansen, og
``catalog/metrics.yml:utflyttere_fifa_differanse`` for forbeholdene — først
og fremst at dette *er* satire, og at en FIFA-plassering ikke måler noe av
verdi ved å bo et sted.

Ingen bilder av virkelige ansikter: tabellen tegnes som fotballkort-stil SVG
med flaggfarger, landskoder og tegnede glad/sint-fjes (ikke portretter) som
uttrykker opp- eller nedrykk. Se ``_utflyttertabell_svg`` under.

Kjør:  uv run statman example utflyttere-fifa
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import polars as pl

from statman import io, publish
from statman.sources import fifa, utflyttere

SLUG: Final[str] = "utflyttere_fifa"
MODEL: Final[str] = "mart.utflyttere_fifa"
MODELS: Final[list[str]] = [MODEL]
METRICS: Final[tuple[str, ...]] = ("utflyttere_fifa_differanse",)

# Flaggfarger per FIFA-lagkode — forenklede stripesett, ikke geometrisk
# korrekte flagg. Nok til å signalisere landet uten å late som noe annet.
_FLAGG: Final[dict[str, tuple[str, str, str]]] = {
    "SUI": ("#d52b1e", "#ffffff", "#d52b1e"),
    "CYP": ("#ffffff", "#d57800", "#4e7a25"),
    "ENG": ("#ffffff", "#ce1124", "#ffffff"),
    "USA": ("#b22234", "#ffffff", "#3c3b6e"),
    "UAE": ("#ce1126", "#00732f", "#000000"),
}

# Kortere visningsnavn for ruta i kortet, der det formelle landnavnet er for
# langt til å få plass på én linje. Prosa og kilder bruker fortsatt
# ``land_navn`` uavkortet.
_KORTNAVN: Final[dict[str, str]] = {
    "De forente arabiske emirater": "Emiratene",
}

_GRONN: Final[str] = "#1f6f4a"
_ROD: Final[str] = "#a33b32"
_BLEKK: Final[str] = "#16150f"
_DEMPET: Final[str] = "#6d675e"
_PAPIR: Final[str] = "#fbfaf7"
_STREK: Final[str] = "#e6e1d8"


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def ingest() -> dict[str, Path]:
    """Frys FIFA-rangeringen og utflytterroasteret til rålaget."""
    return {
        "fifa": fifa.fetch(),
        "utflyttere": utflyttere.ingest(),
    }


# --------------------------------------------------------------------------
# Grafikk — fotballkort-stil SVG, ingen fotografier
# --------------------------------------------------------------------------
def _ansikt(fx: float, fy: float, r: float, *, glad: bool) -> str:
    """Tegnet fjes: runde øyne alltid, øyenbryn og munn avgjør uttrykket."""
    farge = _GRONN if glad else _ROD
    deler = [f'<circle cx="{fx}" cy="{fy}" r="{r}" fill="{farge}"/>']

    for sign in (-1, 1):
        ex = fx + sign * r * 0.36
        ey = fy - r * 0.12
        deler.append(f'<circle cx="{ex}" cy="{ey}" r="{r * 0.19}" fill="#fff"/>')
        deler.append(f'<circle cx="{ex}" cy="{ey}" r="{r * 0.085}" fill="{_BLEKK}"/>')
        if glad:
            bx0, by0 = fx + sign * r * 0.58, fy - r * 0.42
            bx1, by1 = fx + sign * r * 0.20, fy - r * 0.5
        else:
            bx0, by0 = fx + sign * r * 0.58, fy - r * 0.5
            bx1, by1 = fx + sign * r * 0.16, fy - r * 0.24
        deler.append(
            f'<line x1="{bx0}" y1="{by0}" x2="{bx1}" y2="{by1}" '
            f'stroke="#fff" stroke-width="{r * 0.1}" stroke-linecap="round"/>'
        )

    if glad:
        deler.append(
            f'<path d="M {fx - r * 0.42} {fy + r * 0.38} '
            f'Q {fx} {fy + r * 0.74} {fx + r * 0.42} {fy + r * 0.38}" '
            f'stroke="#fff" stroke-width="{r * 0.095}" fill="none" stroke-linecap="round"/>'
        )
    else:
        deler.append(
            f'<path d="M {fx - r * 0.4} {fy + r * 0.56} '
            f'Q {fx} {fy + r * 0.3} {fx + r * 0.4} {fy + r * 0.56}" '
            f'stroke="#fff" stroke-width="{r * 0.095}" fill="none" stroke-linecap="round"/>'
        )

    bx, by = fx + r * 0.86, fy - r * 0.86
    deler.append(f'<circle cx="{bx}" cy="{by}" r="{r * 0.34}" fill="{_PAPIR}" stroke="{farge}" stroke-width="2.5"/>')
    if glad:
        pil = f"M {bx} {by - r * 0.17} L {bx - r * 0.14} {by + r * 0.1} L {bx + r * 0.14} {by + r * 0.1} Z"
    else:
        pil = f"M {bx} {by + r * 0.17} L {bx - r * 0.14} {by - r * 0.1} L {bx + r * 0.14} {by - r * 0.1} Z"
    deler.append(f'<path d="{pil}" fill="{farge}"/>')
    return "".join(deler)


def _rutestorrelse(land_navn: str) -> int:
    """Skriftstørrelse for Norge->land-linja — krymper for lange landnavn."""
    tekst = _KORTNAVN.get(land_navn, land_navn)
    return 13 if len(tekst) <= 12 else 11


def _kort(x: float, row: dict, *, index: int) -> str:
    w, h = 258.0, 460.0
    glad = bool(row["rykket_opp"])
    farge = _GRONN if glad else _ROD
    flagg = _FLAGG.get(row["fifa_kode"], ("#999", "#ccc", "#999"))
    clip_id = f"kort-{index}"
    stripebredde = w / 3

    stripes = "".join(
        f'<rect x="{i * stripebredde}" y="0" width="{stripebredde + 0.5}" height="56" fill="{c}"/>'
        for i, c in enumerate(flagg)
    )

    fortegn = "+" if row["differanse"] > 0 else "−"
    diff_tekst = f"{fortegn}{abs(row['differanse'])}"

    return f"""
<g transform="translate({x},0)">
  <clipPath id="{clip_id}"><rect width="{w}" height="{h}" rx="20"/></clipPath>
  <rect x="3" y="5" width="{w}" height="{h}" rx="20" fill="#000" opacity="0.07"/>
  <rect width="{w}" height="{h}" rx="20" fill="#fff" stroke="{_STREK}"/>
  <g clip-path="url(#{clip_id})">{stripes}</g>
  <rect x="{w - 76}" y="14" width="60" height="28" rx="14" fill="#fff" opacity="0.94"/>
  <text x="{w - 46}" y="33" text-anchor="middle" font-family="var(--sans)"
        font-weight="700" font-size="15" fill="{_BLEKK}">{row['fifa_kode']}</text>
  {_ansikt(w / 2, 148, 62, glad=glad)}
  <text x="{w / 2}" y="240" text-anchor="middle" font-weight="700" font-size="19"
        fill="{_BLEKK}">{_esc(row['navn'])}</text>
  <text x="{w / 2}" y="262" text-anchor="middle" font-size="13" fill="{_DEMPET}"
        font-style="italic">{_esc(row['sted'])}, {row['flyttet_aar']}</text>
  <line x1="24" y1="284" x2="{w - 24}" y2="284" stroke="{_STREK}"/>
  <text x="{w / 2}" y="308" text-anchor="middle" font-size="{_rutestorrelse(row['land_navn'])}" fill="{_DEMPET}">
    Norge (#{row['norge_rangering']}) &#8594; {_esc(_KORTNAVN.get(row['land_navn'], row['land_navn']))} (#{row['land_rangering']})
  </text>
  <text x="{w / 2}" y="372" text-anchor="middle" font-weight="800" font-size="56"
        fill="{farge}">{diff_tekst}</text>
  <text x="{w / 2}" y="396" text-anchor="middle" font-size="12" letter-spacing="0.06em"
        fill="{_DEMPET}">PLASSER {'OPP' if glad else 'NED'}</text>
  <text x="{w / 2}" y="{h - 18}" text-anchor="middle" font-size="11" fill="{_DEMPET}"
        font-style="italic">Kilde: {_esc(row['kilde_navn'])}</text>
</g>"""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def utflyttertabell_svg(df: pl.DataFrame, norge_rangering: int) -> str:
    """Fotballkort-stil SVG: én ruteper utflytter, flagg, landskode og tegnet fjes."""
    rader = df.sort("differanse", descending=True).to_dicts()
    n = len(rader)
    kort_w, gap, margin = 258.0, 22.0, 40.0
    total_w = margin * 2 + n * kort_w + (n - 1) * gap
    total_h = 620.0

    kort = "".join(
        f'<g transform="translate({margin + i * (kort_w + gap)},130)">{_kort(0, row, index=i)}</g>'
        for i, row in enumerate(rader)
    )

    return f"""<svg viewBox="0 0 {total_w:.0f} {total_h:.0f}" xmlns="http://www.w3.org/2000/svg"
     font-family="ui-sans-serif, system-ui, 'Segoe UI', Roboto, Helvetica, sans-serif">
  <rect width="{total_w:.0f}" height="{total_h:.0f}" fill="{_PAPIR}"/>
  <text x="{margin}" y="52" font-weight="800" font-size="30" fill="{_BLEKK}">Utflyttertabellen</text>
  <text x="{margin}" y="82" font-size="15" fill="{_DEMPET}">Norge ligger på {norge_rangering}. plass på FIFA-rankingen. Slik ligger de nye hjemlandene.</text>
  {kort}
</svg>"""


# --------------------------------------------------------------------------
# Artikkel
# --------------------------------------------------------------------------
def artikkel(df: pl.DataFrame, bygg: dict) -> publish.Article:
    norge_rangering = int(df["norge_rangering"][0])
    opp = df.filter(pl.col("rykket_opp"))
    ned = df.filter(~pl.col("rykket_opp"))

    kilder = publish.Findings(
        tuple(
            f"**{r['navn']}** → {r['land_navn']} ({r['sted']}, {r['flyttet_aar']}): "
            f"{r['notat']} Kilde: {r['kilde_navn']}."
            for r in df.sort("differanse", descending=True).to_dicts()
        )
    )

    funn = publish.Section(
        "Tabellen",
        (
            publish.Stats(
                (
                    publish.Stat(str(norge_rangering), "Norges plass", "FIFA/Coca-Cola Men's World Ranking, menn"),
                    publish.Stat(str(opp.height), "Rykket opp", "nytt hjemland bedre plassert enn Norge"),
                    publish.Stat(str(ned.height), "Rykket ned", "nytt hjemland dårligere plassert enn Norge"),
                )
            ),
            publish.Figure(
                "utflyttertabell.svg",
                alt="Fire fotballkort-stiliserte ruter, én per utflytter, med flaggfarger, "
                "landskode, tegnet glad- eller sint-fjes og differansen mot Norges FIFA-plassering.",
                caption="Rykket opp eller ned: det nye hjemlandets FIFA-plassering minus Norges.",
                source="Kilde: FIFA/Coca-Cola Men's World Ranking (gjeldende fra 20. juli 2026).",
                width="full",
            ),
        ),
    )

    metode = publish.Section(
        "Hvem, hvor, og hvorfor de teller med",
        (kilder,),
    )

    return publish.Article(
        slug=SLUG,
        kicker="Satire · Skatteutflyttere mot FIFA-rankingen",
        title="De får ikke lenger heie på Norge — men gjorde de et godt bytte?",
        lead=(
            "En utflytter mister retten til å heie på Norge og må heie på sitt nye "
            "hjemland i stedet. Vi lot FIFA/Coca-Cola Men's World Ranking avgjøre om "
            "det var et godt bytte: Norges plassering minus det nye landets. "
            f"Fasit: {opp.height} rykket opp, {ned.height} rykket rått og brutalt ned."
        ),
        published=bygg["built_at"][:10],
        sections=(funn, metode),
        caveats=METRICS,
        provenance={
            "Kilde, FIFA-ranking": "inside.fifa.com/fifa-rankings/world-ranking/men, gjeldende fra 20. juli 2026",
            "Kilde, utflytterroster": "Se kildehenvisning per person i «Hvem, hvor, og hvorfor de teller med»",
            "Modell": MODEL,
            "Bygget": bygg["built_at"][:19].replace("T", " ") + "Z",
        },
        files=(
            (f"{SLUG}.csv", "hele mart.utflyttere_fifa, én rad per utflytter"),
            ("utflyttertabell.svg", "fotballkort-tabellen"),
        ),
    )


# --------------------------------------------------------------------------
def main() -> list[Path]:
    """Bygg sakspakken. Forutsetter at modellen er bygget."""
    df = io.load(MODEL)
    bygg = io.read_manifest(MODEL)
    norge_rangering = int(df["norge_rangering"][0])

    target = io.output_dir() / SLUG
    target.mkdir(parents=True, exist_ok=True)

    csv_path = target / f"{SLUG}.csv"
    df.write_csv(csv_path)

    svg_path = target / "utflyttertabell.svg"
    svg_path.write_text(utflyttertabell_svg(df, norge_rangering), encoding="utf-8")

    art = artikkel(df, bygg)
    art.validate(target)
    return [
        csv_path,
        svg_path,
        publish.markdown.write(art, target / "notat.md"),
        art.write(target),
    ]


if __name__ == "__main__":  # pragma: no cover
    for written in main():
        print(written)
