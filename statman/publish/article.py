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
from dataclasses import MISSING, dataclass, fields, is_dataclass
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


# --------------------------------------------------------------------------
# Figurer som tegnes i sida
# --------------------------------------------------------------------------
# Fargeroller, ikke farger. Analysen sier *hva* et merke er — vekst, fall,
# den første kategorien — og publiseringslaget bestemmer hvilken farge det
# blir. Slik kan paletten byttes ett sted når den ikke består
# fargeblindhetssjekken, uten å røre en eneste analyse. Rekkefølgen er fast:
# «kat3» tas i bruk fordi det er en tredje kategori, aldri fordi den ser fin ut.
TONES_KATEGORI: tuple[str, ...] = ("vekst", "fall", "kat1", "kat2", "kat3", "kat4", "noytral")

# De to ordnede vokabularene. Forskjellen fra de kategoriske er ikke at de er
# flere, men at *rekkefølgen bærer mening*: skala3 ligger mellom skala2 og
# skala4, og det gjør den i alle tre fargesyn fordi lysheten er monoton.
# Kategoriske roller har ingen rekkefølge, og skal ikke brukes til å vise en
# mengde. Å velge hvilket trinn en verdi havner på er en inndeling, altså et
# valg, og hører derfor i analysen — ikke her.
TONES_SKALA: tuple[str, ...] = ("skala1", "skala2", "skala3", "skala4", "skala5")

# Divergerende: avvik3 er midten, og de to endene peker hver sin vei. Brukes
# der fortegnet er poenget — vekst mot nedgang — og aldri der verdien bare er
# stor eller liten.
TONES_AVVIK: tuple[str, ...] = ("avvik1", "avvik2", "avvik3", "avvik4", "avvik5")

# Ikke en verdi, men fraværet av en. Egen rolle framfor «noytral», fordi
# «kilden publiserer ikke dette tallet» og «tallet er null» er to forskjellige
# opplysninger som ikke skal se like ut.
TONE_MANGLER: str = "mangler"

TONES: tuple[str, ...] = (
    *TONES_KATEGORI, *TONES_SKALA, *TONES_AVVIK, TONE_MANGLER
)


@dataclass(frozen=True, slots=True)
class Axis:
    """En akse med ferdig valgte merker og ferdig formaterte merketekster.

    ``lo`` og ``hi`` er utsnittet. De er et valg — hvor mye av halen som får
    være med — og hører derfor hjemme i analysen, ikke i rendereren.
    """

    label: str = ""
    lo: float = 0.0
    hi: float = 1.0
    ticks: tuple[float, ...] = ()
    tick_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Readout:
    """En linje i boblen som vises når leseren peker på et merke."""

    label: str
    value: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Guide:
    """En hjelpelinje med navn: «nullvekst», en terskel, et landssnitt.

    ``kind`` er ``"x"``, ``"y"`` eller ``"diagonal"``. ``labels`` med ett
    element settes ved linja; med to settes ett på hver side, som når en
    delelinje skiller to opptalte grupper fra hverandre.
    """

    kind: str
    at: float = 0.0
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Layer:
    """Ett fargelag i en figur som kan farges på flere måter.

    Et flisediagram har én oppdeling av flaten og mange måter å farge den
    på: lønn, kvinneandel, vekst, alder. Laget er den ene av dem, med
    tegnforklaringen som gjelder akkurat den.

    ``legend`` er ``(tone, tekst)`` og forklarer hva trinnene betyr *i dette
    laget* — «under 40 000 kr», ikke «skala1». Uten den er en ordnet skala
    bare fem farger.
    """

    key: str
    label: str
    legend: tuple[tuple[str, str], ...] = ()
    caption: str = ""


@dataclass(frozen=True, slots=True)
class Mark:
    """Ett merke: en prikk i en sky, en strek i en stripe, en rad med søyler.

    ``values`` er det boblen viser, ferdig formatert. ``segments`` er
    ``(tone, verdi)`` for stablede søyler; positive ledd vokser høyre for
    null, negative venstre, slik at et negativt bidrag trekker totalen ned
    i stedet for å legge seg oppå.

    ``tones`` er én rolle per lag i en figur med :class:`Layer`-lag, i samme
    rekkefølge som lagene. ``tone`` gjelder når figuren ikke har lag.
    """

    label: str
    group: str = ""
    x: float = 0.0
    y: float = 0.0
    size: float = 1.0
    tone: str = "noytral"
    values: tuple[Readout, ...] = ()
    segments: tuple[tuple[str, float], ...] = ()
    note: str = ""
    pin: bool = False
    tones: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chart:
    """En figur som tegnes i sida, med en PNG under seg.

    ``fallback`` er den samme matplotlib-figuren som før. Den står i notatet,
    den står i sida til skriptet har tegnet ferdig, og den blir stående for en
    leser uten JavaScript. Figuren er altså aldri *avhengig* av å være
    interaktiv — interaktiviteten er noe som kommer i tillegg.

    Merk hva blokka *ikke* inneholder: ingen farger, ingen pikselstørrelser,
    og ingen serier rendereren kan finne på å summere. Den bærer tallene
    analysen valgte, og tegner nøyaktig dem.

    ``link`` kobler flere figurer til samme markering: velger leseren en
    kommune, framheves den i alle figurer med samme ``link``. ``picker`` er
    etiketten over nedtrekket, og settes bare på én figur per gruppe.
    """

    KIND: ClassVar[str] = "chart"
    kind: str
    marks: tuple[Mark, ...]
    fallback: str
    alt: str
    x: Axis | None = None
    y: Axis | None = None
    legend: tuple[tuple[str, str], ...] = ()
    guides: tuple[Guide, ...] = ()
    link: str = ""
    picker: str = ""
    group_label: str = ""
    caption: str = ""
    source: str = ""
    width: str = "bred"
    layers: tuple[Layer, ...] = ()
    layer_label: str = ""

    def spec(self) -> dict[str, Any]:
        """Figuren som json-klare data — det sida får å tegne etter."""
        return _block_to_dict(self)

    def tones(self) -> tuple[str, ...]:
        """Alle fargeroller figuren viser til. Brukes av ``validate``."""
        brukt: list[str] = [tone for tone, _ in self.legend]
        for lag in self.layers:
            brukt += [tone for tone, _ in lag.legend]
        for mark in self.marks:
            brukt.append(mark.tone)
            brukt += mark.tones
            brukt += [tone for tone, _ in mark.segments]
            brukt += [r.tone for r in mark.values if r.tone]
        return tuple(brukt)


KINDS: tuple[str, ...] = ("scatter", "strip", "bars", "treemap")

# Figurtyper som kan farges på flere måter. Lag på en figurtype som ikke står
# her ville blitt skrevet til fila og aldri tegnet — leseren hadde fått en
# velger som ikke gjorde noe.
KINDS_MED_LAG: tuple[str, ...] = ("treemap",)

Block = Union[Prose, Findings, Stats, Figure, Table, Chart]

_BLOCKS: dict[str, type] = {
    cls.KIND: cls  # type: ignore[attr-defined]
    for cls in (Prose, Findings, Stats, Figure, Table, Chart)
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

    def charts(self) -> tuple[Chart, ...]:
        return tuple(
            block
            for section in self.sections
            for block in section.blocks
            if isinstance(block, Chart)
        )

    def assets(self) -> tuple[str, ...]:
        """Alle filer siden trenger ved siden av seg: figurer og nedlastinger.

        PNG-en under en tegnet figur er med her. Den er ikke pynt — den er det
        leseren får uten skript, og den skal derfor ligge i sakspakken på
        nøyaktig samme vilkår som en vanlig figur.
        """
        names = [fig.file for fig in self.figures()]
        names += [chart.fallback for chart in self.charts()]
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
                if isinstance(block, Chart):
                    feil += _sjekk_figur(block, section.title)

        # En markeringsgruppe uten nedtrekk er en figur som lyser opp uten at
        # noen kan få den til å gjøre det. Nøyaktig én figur per gruppe eier
        # velgeren; ellers står det to nedtrekk som styrer det samme.
        grupper: dict[str, list[Chart]] = {}
        for chart in self.charts():
            if chart.link:
                grupper.setdefault(chart.link, []).append(chart)
        for navn, gruppe in grupper.items():
            eiere = [c for c in gruppe if c.picker]
            if len(eiere) != 1:
                feil.append(
                    f"markeringsgruppa {navn!r} har {len(eiere)} figurer med picker, "
                    "og skal ha nøyaktig én"
                )

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
def _sjekk_figur(chart: Chart, seksjon: str) -> list[str]:
    """Sjekkene på en tegnet figur. Hver av dem skal kunne feile."""
    hvor = f"figuren i «{seksjon}»"
    feil: list[str] = []

    if chart.kind not in KINDS:
        feil.append(f"{hvor} har ukjent type {chart.kind!r}. Kjente: {', '.join(KINDS)}")
    if not chart.marks:
        feil.append(f"{hvor} har ingen merker å tegne")
    if not chart.fallback:
        feil.append(f"{hvor} mangler fallback — figuren må ha en PNG under seg")

    # Fargeroller er et lukket vokabular. Slipper vi en ukjent gjennom, blir
    # merket usynlig i sida og feilen oppdages først i nettleseren.
    for tone in chart.tones():
        if tone and tone not in TONES:
            feil.append(
                f"{hvor} bruker fargerollen {tone!r}, som ikke finnes. "
                f"Kjente: {', '.join(TONES)}"
            )

    for navn, akse in (("x", chart.x), ("y", chart.y)):
        if akse is None:
            continue
        if akse.tick_labels and len(akse.ticks) != len(akse.tick_labels):
            feil.append(
                f"{hvor} har {len(akse.ticks)} merker og {len(akse.tick_labels)} "
                f"merketekster på {navn}-aksen"
            )
        if akse.hi <= akse.lo:
            feil.append(f"{hvor} har et tomt utsnitt på {navn}-aksen")

    if chart.kind == "scatter" and (chart.x is None or chart.y is None):
        feil.append(f"{hvor} er et punktdiagram og trenger begge akser")
    if chart.kind == "bars" and any(not m.segments for m in chart.marks):
        feil.append(f"{hvor} er et søylediagram, men har merker uten segmenter")
    if chart.picker and not chart.link:
        feil.append(f"{hvor} har en picker uten link, og styrer da ingenting")

    feil += _sjekk_lag(chart, hvor)

    if chart.kind == "treemap":
        # Flatene *er* påstanden i et flisediagram: at de til sammen utgjør
        # helheten. En negativ størrelse har ingen flate å være, og en figur
        # der alt er null har ingen flate i det hele tatt.
        if any(m.size < 0 for m in chart.marks):
            feil.append(f"{hvor} er et flisediagram med negative størrelser")
        if not any(m.size > 0 for m in chart.marks):
            feil.append(f"{hvor} er et flisediagram der ingen flate har størrelse")

    return feil


def _sjekk_lag(chart: Chart, hvor: str) -> list[str]:
    """Sjekkene på fargelag. Hver av dem skal kunne feile."""
    feil: list[str] = []

    if chart.layers and chart.kind not in KINDS_MED_LAG:
        feil.append(
            f"{hvor} har fargelag, men {chart.kind!r} tegnes uten dem. "
            f"Typer med lag: {', '.join(KINDS_MED_LAG)}"
        )
    if chart.layer_label and not chart.layers:
        feil.append(f"{hvor} har en lagvelger uten lag, og styrer da ingenting")

    if not chart.layers:
        return feil

    nokler = [lag.key for lag in chart.layers]
    if len(set(nokler)) != len(nokler):
        feil.append(f"{hvor} har to fargelag med samme nøkkel")
    for lag in chart.layers:
        if not lag.key or not lag.label:
            feil.append(f"{hvor} har et fargelag uten nøkkel eller etikett")

    # Et merke som mangler en rolle i ett av lagene ville blitt usynlig i
    # nettopp det laget, og bare der. Det er den slags feil som ikke oppdages
    # før noen bytter lag i nettleseren.
    ventet = len(chart.layers)
    mangler = [m.label for m in chart.marks if len(m.tones) != ventet]
    if mangler:
        feil.append(
            f"{hvor} har {ventet} fargelag, men {len(mangler)} merker oppgir "
            f"et annet antall roller (f.eks. {mangler[0]!r})"
        )
    return feil


# --------------------------------------------------------------------------
def _block_to_dict(block: Block) -> dict[str, Any]:
    data: dict[str, Any] = {"type": block.KIND}
    for f in fields(block):
        data[f.name] = _plain(getattr(block, f.name))
    return data


# Delene av en figur som skrives kompakt: felt som står på sin egen
# standardverdi utelates. En sky på 323 kommuner har ellers «"segments":[],
# "note":"","pin":false» på hver eneste av dem, og det er hundre kilobyte som
# ikke sier noe. Lesingen fyller standardverdiene inn igjen, så rundturen er
# uendret. Bare de nye typene komprimeres — de gamle blokkene skal beholde
# formen sin, så ingen publisert artikkel.json endrer seg uten grunn.
_KOMPAKTE: tuple[type, ...] = (Axis, Readout, Guide, Mark, Layer)


def _plain(value: Any) -> Any:
    """Dataklasser og tupler ned til det json kan bære."""
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        kompakt = isinstance(value, _KOMPAKTE)
        ut: dict[str, Any] = {}
        for f in fields(value):
            rå = getattr(value, f.name)
            if kompakt and f.default is not MISSING and rå == f.default:
                continue
            ut[f.name] = _plain(rå)
        return ut
    return value


def _block_from_dict(data: dict[str, Any]) -> Block:
    kind = data.get("type")
    cls = _BLOCKS.get(str(kind))
    if cls is None:
        raise ValueError(f"Ukjent blokktype {kind!r}. Kjente: {', '.join(sorted(_BLOCKS))}")
    kwargs = {k: v for k, v in data.items() if k != "type"}
    if cls is Stats:
        return Stats(items=tuple(Stat(**item) for item in kwargs.get("items", [])))
    if cls is Chart:
        return _chart_from_dict(kwargs)
    return cls(**{k: _tuples(v) for k, v in kwargs.items()})  # type: ignore[arg-type]


def _chart_from_dict(data: dict[str, Any]) -> Chart:
    """Figuren tilbake fra json, med de nøstede delene bygget som seg selv.

    Skrevet ut for hånd framfor å gjettes fram med refleksjon: en figur som
    kommer skjevt tilbake fra fila er en feil vi vil se her, ikke som et tomt
    felt i nettleseren.
    """

    def akse(rå: Any) -> Axis | None:
        if not rå:
            return None
        return Axis(
            label=str(rå.get("label", "")),
            lo=float(rå.get("lo", 0.0)),
            hi=float(rå.get("hi", 1.0)),
            ticks=tuple(float(t) for t in rå.get("ticks") or ()),
            tick_labels=tuple(str(t) for t in rå.get("tick_labels") or ()),
        )

    def merke(rå: dict[str, Any]) -> Mark:
        return Mark(
            label=str(rå.get("label", "")),
            group=str(rå.get("group", "")),
            x=float(rå.get("x", 0.0)),
            y=float(rå.get("y", 0.0)),
            size=float(rå.get("size", 1.0)),
            tone=str(rå.get("tone", "noytral")),
            values=tuple(
                Readout(
                    label=str(v.get("label", "")),
                    value=str(v.get("value", "")),
                    tone=str(v.get("tone", "")),
                )
                for v in rå.get("values") or ()
            ),
            segments=tuple((str(t), float(v)) for t, v in rå.get("segments") or ()),
            note=str(rå.get("note", "")),
            pin=bool(rå.get("pin", False)),
            tones=tuple(str(t) for t in rå.get("tones") or ()),
        )

    def lag(rå: dict[str, Any]) -> Layer:
        return Layer(
            key=str(rå.get("key", "")),
            label=str(rå.get("label", "")),
            legend=tuple((str(t), str(s)) for t, s in rå.get("legend") or ()),
            caption=str(rå.get("caption", "")),
        )

    return Chart(
        kind=str(data.get("kind", "")),
        marks=tuple(merke(m) for m in data.get("marks") or ()),
        fallback=str(data.get("fallback", "")),
        alt=str(data.get("alt", "")),
        x=akse(data.get("x")),
        y=akse(data.get("y")),
        legend=tuple((str(t), str(s)) for t, s in data.get("legend") or ()),
        guides=tuple(
            Guide(
                kind=str(g.get("kind", "")),
                at=float(g.get("at", 0.0)),
                labels=tuple(str(s) for s in g.get("labels") or ()),
            )
            for g in data.get("guides") or ()
        ),
        link=str(data.get("link", "")),
        picker=str(data.get("picker", "")),
        group_label=str(data.get("group_label", "")),
        caption=str(data.get("caption", "")),
        source=str(data.get("source", "")),
        width=str(data.get("width", "bred")),
        layers=tuple(lag(l) for l in data.get("layers") or ()),
        layer_label=str(data.get("layer_label", "")),
    )


def _tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuples(v) for v in value)
    return value
