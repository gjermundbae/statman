"""Publiseringslaget — sakspakke til artikkel.

Det sjette laget. Reglene i de fem andre sier hva som ikke får skje der;
regelen her er at **ingen vurdering tas**. Alle tall kommer ferdig formatert
inn med :class:`~statman.publish.article.Article`, alle forbehold kommer fra
metrikkatalogen. En renderer som ikke velger, kan heller ikke velge feil.

Regelen het lenge «ingenting regnes ut», og for alt uten tidslinje er det
fortsatt det samme. En figur med :class:`~statman.publish.article.Timeline`
lar leseren velge tidspunktet, og da finnes ikke svaret på forhånd — det er
for mange av dem. Der sier analysen regelen i stedet for svaret: hvilken
serie som måles, hvilke grenser trinnene går ved, hvor mange desimaler
tallet tåler. Sida bruker den og finner ikke på noe.

    from statman.publish import Article, Section, Findings, markdown

    art = Article(slug="min-sak", title="…", lead="…", sections=(...))
    art.write(pakke)                    # artikkel.json — seamen mot publisering
    markdown.write(art, pakke / "notat.md")

Deretter, når du er fornøyd:  ``statman publish min-sak``
"""

from statman.publish.article import (
    Article,
    Axis,
    Chart,
    Figure,
    Findings,
    Format,
    Guide,
    Layer,
    Mark,
    Prose,
    Readout,
    Section,
    Stat,
    Stats,
    Table,
    Timeline,
)
from statman.publish import html, markdown, site

__all__ = [
    "Article",
    "Axis",
    "Chart",
    "Figure",
    "Findings",
    "Format",
    "Guide",
    "Layer",
    "Mark",
    "Prose",
    "Readout",
    "Section",
    "Stat",
    "Stats",
    "Table",
    "Timeline",
    "html",
    "markdown",
    "site",
]
