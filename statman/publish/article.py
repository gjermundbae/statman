"""Artikkelen som struktur, ikke som prosa.

En :class:`Article` er det en ferdig analyse har å si, satt opp slik at det kan
skrives ut i flere former uten å bli skrevet på nytt. Notatet i sakspakken og
den publiserte siden rendres begge herfra, så de kan ikke gli fra hverandre.

Modellen kjenner ikke til DuckDB, Polars eller matplotlib. Alt som kommer inn
er ferdig formatert tekst og ferdig valgte tall — publiseringslaget regner
ingenting ut, og kan derfor ikke regne feil. Det er hele poenget med at det er
et eget lag.

Forbehold oppgis som *nøkler* inn i ``catalog/metrics.yml``, aldri som tekst.
Skriver du dem av for hånd her, har du laget en kopi som forvitrer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, ClassVar, Union

SCHEMA: str = "statman/artikkel/1"
FILENAME: str = "artikkel.json"


# --------------------------------------------------------------------------
# Blokker
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Prose:
    """Et avsnitt. ``**fet**``, ``*kursiv*`` og ``` `kode` ``` tolkes."""

    KIND: ClassVar[str] = "prose"
    text: str


@dataclass(frozen=True, slots=True)
class Findings:
    """En punktliste. Det som i notatet står under «Funn»."""

    KIND: ClassVar[str] = "findings"
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stat:
    """Ett nøkkeltall. ``value`` er ferdig formatert — «+14,4 %», ikke 0.1437."""

    value: str
    label: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Stats:
    KIND: ClassVar[str] = "stats"
    items: tuple[Stat, ...]


@dataclass(frozen=True, slots=True)
class Figure:
    """En figur som ligger i sakspakken.

    ``file`` er filnavnet slik det står i ``output/<slug>/``. Bredden er et
    valg om hvor mye plass figuren får bryte ut av tekstspennet: ``"tekst"``,
    ``"bred"`` eller ``"full"``.
    """

    KIND: ClassVar[str] = "figure"
    file: str
    alt: str
    caption: str = ""
    source: str = ""
    width: str = "bred"


@dataclass(frozen=True, slots=True)
class Table:
    """En tabell med ferdig formaterte celler.

    ``align`` er ``"left"`` eller ``"right"`` per kolonne, og styrer både
    markdown-justeringen og HTML-en. Tom betyr venstre hele veien.
    """

    KIND: ClassVar[str] = "table"
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    align: tuple[str, ...] = ()
    caption: str = ""

    def alignment(self) -> tuple[str, ...]:
        if self.align:
            return self.align
        return tuple("left" for _ in self.columns)


Block = Union[Prose, Findings, Stats, Figure, Table]

_BLOCKS: dict[str, type] = {
    cls.KIND: cls for cls in (Prose, Findings, Stats, Figure, Table)  # type: ignore[attr-defined]
}


# --------------------------------------------------------------------------
# Seksjon og artikkel
# --------------------------------------------------------------------------
def slugify(text: str) -> str:
    """«Fylker og kommuner» -> «fylker-og-kommuner». Brukes til ankere.

    Understrek beholdes, så en artikkel kan hete det samme som mappa
    sakspakken ligger i — ``befolkningsvekst_kommune`` er både katalognavnet
    i ``output/`` og adressen på nett.
    """
    lower = text.lower()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa")):
        lower = lower.replace(a, b)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9_]+", "-", lower)).strip("-") or "del"


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    blocks: tuple[Block, ...]

    @property
    def anchor(self) -> str:
        return slugify(self.title)


@dataclass(frozen=True, slots=True)
class Article:
    """En ferdig sakspakke, klar til å skrives ut.

    ``caveats`` er metrikknøkler. ``provenance`` er en ordnet dict fra
    etikett til verdi — den blir kvitteringen nederst på siden, og innholdet
    skal komme fra byggeloggen, ikke fra et nytt oppslag mot rådata.
    ``files`` er ``(filnavn, beskrivelse)`` for det sakspakken inneholder.
    """

    slug: str
    title: str
    lead: str
    sections: tuple[Section, ...]
    kicker: str = ""
    published: str = ""
    caveats: tuple[str, ...] = ()
    provenance: dict[str, str] | None = None
    files: tuple[tuple[str, str], ...] = ()

    # ----------------------------------------------------------------
    def figures(self) -> tuple[Figure, ...]:
        return tuple(
            block
            for section in self.sections
            for block in section.blocks
            if isinstance(block, Figure)
        )

    def assets(self) -> tuple[str, ...]:
        """Alle filer siden trenger ved siden av seg: figurer og nedlastinger."""
        names = [fig.file for fig in self.figures()]
        names += [name for name, _ in self.files]
        seen: dict[str, None] = {}
        for name in names:
            seen.setdefault(name, None)
        return tuple(seen)

    # ----------------------------------------------------------------
    def validate(self, package: Path | None = None) -> None:
        """Sjekker som skal kunne feile, kjørt før noe skrives.

        Sakspakken er en mappe med filer og notatet er allerede skrevet, så
        en artikkel som viser til en figur som ikke finnes, eller til et
        forbehold katalogen ikke har, er en feil vi vil se her og ikke i
        nettleseren.
        """
        from statman import catalog as catalog_mod

        feil: list[str] = []

        if not self.slug or slugify(self.slug) != self.slug:
            feil.append(f"slug {self.slug!r} må være små bokstaver, tall og bindestrek")
        if not self.title:
            feil.append("artikkelen mangler tittel")
        if not self.sections:
            feil.append("artikkelen har ingen seksjoner")

        kjente = catalog_mod.metrics()
        for key in self.caveats:
            if key not in kjente:
                feil.append(
                    f"forbeholdet {key!r} finnes ikke i katalogen. "
                    f"Kjente: {', '.join(sorted(kjente)) or '(tom)'}"
                )

        if package is not None:
            for name in self.assets():
                if not (package / name).exists():
                    feil.append(f"filen {name!r} ligger ikke i sakspakken ({package})")

        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, Table):
                    bredde = len(block.columns)
                    if block.align and len(block.align) != bredde:
                        feil.append(
                            f"tabellen i «{section.title}» har {len(block.align)} "
                            f"justeringer til {bredde} kolonner"
                        )
                    for i, row in enumerate(block.rows):
                        if len(row) != bredde:
                            feil.append(
                                f"tabellen i «{section.title}» har {len(row)} celler "
                                f"i rad {i + 1}, men {bredde} kolonner"
                            )
                            break

        if feil:
            raise ValueError("Artikkelen kan ikke publiseres:\n  " + "\n  ".join(feil))

    # ----------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "slug": self.slug,
            "title": self.title,
            "kicker": self.kicker,
            "lead": self.lead,
            "published": self.published,
            "sections": [
                {"title": s.title, "blocks": [_block_to_dict(b) for b in s.blocks]}
                for s in self.sections
            ],
            "caveats": list(self.caveats),
            "provenance": dict(self.provenance or {}),
            "files": [list(pair) for pair in self.files],
        }

    def write(self, package: Path) -> Path:
        """Skriv ``artikkel.json`` i sakspakken. Dette er seamen mot publisering."""
        package.mkdir(parents=True, exist_ok=True)
        path = package / FILENAME
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    # ----------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        schema = data.get("schema")
        if schema != SCHEMA:
            raise ValueError(f"Ukjent artikkelskjema {schema!r}, ventet {SCHEMA!r}")
        return cls(
            slug=str(data["slug"]),
            title=str(data["title"]),
            kicker=str(data.get("kicker", "")),
            lead=str(data.get("lead", "")),
            published=str(data.get("published", "")),
            sections=tuple(
                Section(
                    title=str(s["title"]),
                    blocks=tuple(_block_from_dict(b) for b in s.get("blocks", [])),
                )
                for s in data.get("sections", [])
            ),
            caveats=tuple(data.get("caveats") or ()),
            provenance=dict(data.get("provenance") or {}),
            files=tuple((str(n), str(d)) for n, d in data.get("files") or ()),
        )

    @classmethod
    def read(cls, package: Path) -> "Article":
        path = package if package.is_file() else package / FILENAME
        if not path.exists():
            raise FileNotFoundError(
                f"Ingen {FILENAME} i {package}. Sakspakken er laget før "
                "publiseringslaget fantes, eller analysen skriver den ikke."
            )
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------
def _block_to_dict(block: Block) -> dict[str, Any]:
    data: dict[str, Any] = {"type": block.KIND}
    for f in fields(block):
        data[f.name] = _plain(getattr(block, f.name))
    return data


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, Stat):
        return {"value": value.value, "label": value.label, "note": value.note}
    return value


def _block_from_dict(data: dict[str, Any]) -> Block:
    kind = data.get("type")
    cls = _BLOCKS.get(str(kind))
    if cls is None:
        raise ValueError(f"Ukjent blokktype {kind!r}. Kjente: {', '.join(sorted(_BLOCKS))}")
    kwargs = {k: v for k, v in data.items() if k != "type"}
    if cls is Stats:
        return Stats(items=tuple(Stat(**item) for item in kwargs.get("items", [])))
    return cls(**{k: _tuples(v) for k, v in kwargs.items()})  # type: ignore[arg-type]


def _tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuples(v) for v in value)
    return value
