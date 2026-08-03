"""Article -> én selvstendig HTML-side.

Sida er ett dokument. CSS og JS legges inn i fila, det finnes ingen fonter,
biblioteker eller sporing utenfra, og ingenting lastes over nettet. Åpner du
fila fra disk, ser den ut som den gjør på GitHub Pages.

Renderen regner ikke. Tall kommer ferdig formatert fra sakspakken, forbehold
kommer fra katalogen. Det den bestemmer er hvordan det ser ut — og der er den
til gjengjeld tydelig.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from statman import catalog as catalog_mod
from statman.publish.article import (
    Article,
    Figure,
    Findings,
    Prose,
    Stats,
    Table,
)

ASSETS = Path(__file__).parent / "assets"

_MAANEDER = (
    "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
)


def asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Tekst
# --------------------------------------------------------------------------
_INLINE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|\*([^*]+?)\*", re.S)


def esc(text: str) -> str:
    return _html.escape(str(text), quote=True)


def inline(text: str) -> str:
    """``**fet**``, ``*kursiv*`` og ``` `kode` `` -> HTML. Alt annet escapes.

    Escapingen skjer først, og innfører verken backtick eller stjerne, så
    mønsteret under kan ikke treffe noe brukeren ikke skrev selv.
    """

    def bytt(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return f"<code>{m.group(1)}</code>"
        if m.group(2) is not None:
            return f"<strong>{m.group(2)}</strong>"
        return f"<em>{m.group(3)}</em>"

    return _INLINE.sub(bytt, esc(text))


def norsk_dato(iso: str) -> str:
    """``"2026-08-03"`` -> ``"3. august 2026"``. Ugyldig inn gir uendret ut."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso
    aar, maaned, dag = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= maaned <= 12:
        return iso
    return f"{dag}. {_MAANEDER[maaned - 1]} {aar}"


# --------------------------------------------------------------------------
# Blokker
# --------------------------------------------------------------------------
def _figur(block: Figure) -> str:
    bredde = block.width if block.width in {"tekst", "bred", "full"} else "bred"
    tekst = ""
    if block.caption or block.source:
        kilde = f'<span class="kilde">{inline(block.source)}</span>' if block.source else ""
        tekst = f"<figcaption>{inline(block.caption)}{kilde}</figcaption>"
    return (
        f'<figure class="figur {bredde} avslor">'
        f'<a href="{esc(block.file)}">'
        f'<img src="{esc(block.file)}" alt="{esc(block.alt)}" loading="lazy" decoding="async">'
        f"</a>{tekst}</figure>"
    )


def _tabell(block: Table) -> str:
    just = block.alignment()
    hode = "".join(
        f'<th scope="col" class="{a}">{inline(c)}</th>' for c, a in zip(block.columns, just)
    )
    kropp = "".join(
        "<tr>" + "".join(f'<td class="{a}">{inline(c)}</td>' for c, a in zip(row, just)) + "</tr>"
        for row in block.rows
    )
    tekst = f'<p class="tabell-tekst">{inline(block.caption)}</p>' if block.caption else ""
    return (
        '<div class="tabell-hylse avslor"><table data-sorterbar>'
        f"<thead><tr>{hode}</tr></thead><tbody>{kropp}</tbody>"
        f"</table></div>{tekst}"
    )


def _stats(block: Stats) -> str:
    celler = "".join(
        f'<div><span class="tall">{esc(s.value)}</span>'
        f'<span class="etikett">{inline(s.label)}</span>'
        + (f'<span class="merknad">{inline(s.note)}</span>' if s.note else "")
        + "</div>"
        for s in block.items
    )
    return f'<div class="noekkeltall avslor">{celler}</div>'


def _block(block: object) -> str:
    if isinstance(block, Prose):
        return f"<p>{inline(block.text)}</p>"
    if isinstance(block, Findings):
        punkter = "".join(f"<li>{inline(item)}</li>" for item in block.items)
        return f'<ul class="funn">{punkter}</ul>'
    if isinstance(block, Stats):
        return _stats(block)
    if isinstance(block, Figure):
        return _figur(block)
    if isinstance(block, Table):
        return _tabell(block)
    raise TypeError(f"Vet ikke hvordan {type(block).__name__} skrives som HTML")


# --------------------------------------------------------------------------
# Deler
# --------------------------------------------------------------------------
def _forbehold(keys: tuple[str, ...]) -> str:
    if not keys:
        return ""
    deler = []
    for key in keys:
        m = catalog_mod.metric(key)
        punkter = "".join(f"<li>{inline(c)}</li>" for c in m.caveats)
        punkter += "".join(
            f'<li class="brudd"><strong>Seriebrudd.</strong> {inline(b)}</li>' for b in m.breaks
        )
        deler.append(
            "<details>"
            f"<summary>{inline(m.label)} <span class=\"enhet\">{inline(m.unit)}</span></summary>"
            f'<p class="kilde-linje">Kilde: {inline(m.source)}</p>'
            f"<ul>{punkter}</ul>"
            "</details>"
        )
    return (
        '<section class="forbehold" id="forbehold"><h2>Forbehold</h2>'
        '<p class="hvorfor">Det som må stå ved siden av tallene for at de skal '
        "kunne forsvares. Hentet fra metrikkatalogen, ikke skrevet på nytt her.</p>"
        + "".join(deler)
        + "</section>"
    )


def _filer(files: tuple[tuple[str, str], ...]) -> str:
    if not files:
        return ""
    punkter = "".join(
        f'<li><a href="{esc(navn)}" download>'
        f'<span class="navn">{esc(navn)}</span>'
        f'<span class="om">{inline(om)}</span></a></li>'
        for navn, om in files
    )
    return f'<section id="filer"><h2>Filer</h2><ul class="filer">{punkter}</ul></section>'


def _kvittering(provenance: dict[str, str] | None) -> str:
    if not provenance:
        return ""
    rader = "".join(
        f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in provenance.items()
    )
    return (
        '<footer class="kvittering"><h2>Statman · kvittering</h2><hr>'
        f"<dl>{rader}</dl><hr>"
        '<p class="bunn">Hvert tall over sporer til hentingen som ga det.</p>'
        "</footer>"
    )


def _merke(hjem: str | None) -> str:
    navn = "Statman"
    inner = f'<a href="{esc(hjem)}">{navn}</a>' if hjem else navn
    return f'<div class="merke"><span class="frø"></span>{inner}</div>'


_FAVICON = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'"
    "%3E%3Crect%20width='32'%20height='32'%20rx='7'%20fill='%231f6f4a'/%3E"
    "%3Crect%20x='8'%20y='17'%20width='4'%20height='8'%20fill='%23fbfaf7'/%3E"
    "%3Crect%20x='14'%20y='11'%20width='4'%20height='14'%20fill='%23fbfaf7'/%3E"
    "%3Crect%20x='20'%20y='7'%20width='4'%20height='18'%20fill='%23fbfaf7'/%3E%3C/svg%3E"
)


def _dokument(*, tittel: str, beskrivelse: str, kropp: str) -> str:
    return f"""<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(tittel)}</title>
<meta name="description" content="{esc(beskrivelse)}">
<meta name="generator" content="statman">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{_FAVICON}">
<style>
{asset("statman.css")}</style>
</head>
<body>
<div class="fremdrift" id="fremdrift"></div>
{kropp}
<script>
{asset("statman.js")}</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Sider
# --------------------------------------------------------------------------
def render(article: Article, *, hjem: str | None = "../index.html") -> str:
    """Hele artikkelsida som én streng."""
    seksjoner = []
    for section in article.sections:
        blokker = "".join(_block(b) for b in section.blocks)
        seksjoner.append(
            f'<section id="{esc(section.anchor)}">'
            f"<h2>{inline(section.title)}</h2>{blokker}</section>"
        )

    stikk = f'<p class="stikk">{inline(article.kicker)}</p>' if article.kicker else ""
    dato = (
        f'<p class="datolinje"><time datetime="{esc(article.published)}">'
        f"{esc(norsk_dato(article.published))}</time></p>"
        if article.published
        else ""
    )

    kropp = (
        f'<article class="ark">{_merke(hjem)}'
        f"<header>{stikk}<h1>{inline(article.title)}</h1>"
        f'<p class="ingress">{inline(article.lead)}</p>{dato}</header>'
        + "".join(seksjoner)
        + _forbehold(article.caveats)
        + _filer(article.files)
        + _kvittering(article.provenance)
        + "</article>"
    )
    return _dokument(tittel=article.title, beskrivelse=article.lead, kropp=kropp)


def render_index(articles: list[Article], *, tittel: str = "Statman") -> str:
    """Arkivet: alt som er publisert, nyeste først."""
    if articles:
        punkter = "".join(
            f'<li><a href="{esc(a.slug)}/index.html">'
            + (f'<p class="stikk">{inline(a.kicker)}</p>' if a.kicker else "")
            + f"<h2>{inline(a.title)}</h2><p>{inline(a.lead)}</p>"
            + (
                f'<time datetime="{esc(a.published)}">{esc(norsk_dato(a.published))}</time>'
                if a.published
                else ""
            )
            + "</a></li>"
            for a in articles
        )
        liste = f'<ul class="arkiv">{punkter}</ul>'
    else:
        liste = '<p class="tomt">Ingen sakspakker publisert ennå.</p>'

    ingress = (
        "Sakspakker fra norsk offentlig statistikk. Hver sak har tallene, "
        "grafene, metoden og forbeholdene på samme side — og en kvittering "
        "nederst som sporer dem tilbake til hentingen som ga dem."
    )
    kropp = (
        f'<article class="ark">{_merke(None)}'
        f'<header><p class="stikk">Arkiv</p><h1>{esc(tittel)}</h1>'
        f'<p class="ingress">{ingress}</p></header>'
        f"<section>{liste}</section></article>"
    )
    return _dokument(tittel=tittel, beskrivelse=ingress, kropp=kropp)


# --------------------------------------------------------------------------
# Sjekk
# --------------------------------------------------------------------------
_EKSTERN = re.compile(r"""(?:src\s*=\s*|url\(\s*)['"]?\s*(https?:|//)""", re.I)


def external_assets(markup: str) -> list[str]:
    """Ressurser sida ville hentet over nettet. Skal alltid være tom.

    Vi ser etter ``src=`` og ``url(``, altså det nettleseren laster av seg
    selv. Vanlige lenker (``href``) er ikke med — de er navigasjon, og en
    artikkel skal få lov til å lenke til kilden sin.
    """
    return [m.group(0) for m in _EKSTERN.finditer(markup)]
