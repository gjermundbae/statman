"""Sakspakke -> publisert side.

Publiseringslaget leser bare fra ``output/``. Aldri fra ``data/``, aldri fra
en modell. Alt det trenger står i ``artikkel.json``, som analysen skrev da den
var ferdig — så en publisering kan ikke komme til å vise andre tall enn dem
som lå i sakspakken du så på og ble fornøyd med.

Arkivet bygges av det som faktisk ligger i ``docs/``, ikke av det som ligger i
``output/``. ``output/`` er gitignorert og er tomt i en fersk klone; ``docs/``
er det som er publisert.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from statman import io
from statman.publish import html as html_mod
from statman.publish.article import FILENAME, Article


class PublishError(RuntimeError):
    """Sakspakken kan ikke publiseres slik den er."""


# --------------------------------------------------------------------------
def packages() -> list[Path]:
    """Sakspakker i ``output/`` som har en artikkel-spesifikasjon."""
    root = io.output_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / FILENAME).exists())


def published() -> list[Article]:
    """Artiklene som ligger i ``docs/``, nyeste først."""
    root = io.docs_dir()
    if not root.is_dir():
        return []
    artikler = [
        Article.read(p) for p in sorted(root.glob(f"*/{FILENAME}"))
    ]
    return sorted(artikler, key=lambda a: (a.published, a.slug), reverse=True)


# --------------------------------------------------------------------------
def publish(package: Path, *, docs: Path | None = None) -> Path:
    """Rendre én sakspakke til ``docs/<slug>/`` og returner sidas sti."""
    article = Article.read(package)
    article.validate(package)

    target = (docs or io.docs_dir()) / article.slug
    target.mkdir(parents=True, exist_ok=True)

    for navn in article.assets():
        shutil.copyfile(package / navn, target / navn)
    shutil.copyfile(package / FILENAME, target / FILENAME)

    markup = html_mod.render(article)
    ekstern = html_mod.external_assets(markup)
    if ekstern:
        raise PublishError(
            f"{article.slug}: sida ville hentet {len(ekstern)} ressurs(er) over nettet "
            f"({', '.join(sorted(set(ekstern)))}). En publisert artikkel skal være "
            "selvstendig og virke uten nett."
        )

    side = target / "index.html"
    side.write_text(markup, encoding="utf-8")
    return side


def write_index(*, docs: Path | None = None) -> Path:
    """Bygg arkivsida på nytt fra det som ligger i ``docs/``."""
    root = docs or io.docs_dir()
    root.mkdir(parents=True, exist_ok=True)
    # GitHub Pages kjører Jekyll som standard, og Jekyll hopper over filer og
    # mapper som starter med understrek. Vi har ingen i dag, men fila koster
    # ingenting og fjerner en klasse feil som er ubehagelig å finne.
    (root / ".nojekyll").write_text("", encoding="utf-8")

    path = root / "index.html"
    path.write_text(html_mod.render_index(published()), encoding="utf-8")
    return path


def publish_all(slugs: list[str] | None = None, *, docs: Path | None = None) -> list[Path]:
    """Publiser navngitte sakspakker, eller alle som har ``artikkel.json``."""
    kandidater = packages()
    klare = {p.name: p for p in kandidater}
    valgt: list[Path] = []
    for slug in slugs or []:
        if slug in klare:
            valgt.append(klare[slug])
        elif (io.output_dir() / slug).is_dir():
            raise PublishError(
                f"Sakspakken {slug!r} har ingen {FILENAME}. Kjør analysen på nytt — "
                "den skriver spesifikasjonen sammen med notatet."
            )
        else:
            kjente = ", ".join(klare) or "(ingen)"
            raise PublishError(f"Ingen sakspakke {slug!r} i output/. Klare: {kjente}")
    valgt = valgt or kandidater

    if not valgt:
        raise PublishError(
            f"Fant ingen sakspakker med {FILENAME} i {io.output_dir()}. "
            "Kjør `statman example <navn>` først."
        )

    sider = [publish(pakke, docs=docs) for pakke in valgt]
    sider.append(write_index(docs=docs))
    return sider
