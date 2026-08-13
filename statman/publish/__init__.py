"""Publiseringslaget — sakspakke til artikkel.

Det sjette laget. Reglene i de fem andre sier hva som ikke får skje der;
regelen her er at **ingenting regnes ut**. Alle tall kommer ferdig formatert
inn med :class:`~statman.publish.article.Article`, alle forbehold kommer fra
metrikkatalogen. En renderer som ikke kan regne, kan heller ikke regne feil.

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
    Guide,
    Layer,
    Mark,
    Prose,
    Readout,
    Section,
    Stat,
    Stats,
    Table,
)
from statman.publish import html, markdown, site

__all__ = [
    "Article",
    "Axis",
    "Chart",
    "Figure",
    "Findings",
    "Guide",
    "Layer",
    "Mark",
    "Prose",
    "Readout",
    "Section",
    "Stat",
    "Stats",
    "Table",
    "html",
    "markdown",
    "site",
]
