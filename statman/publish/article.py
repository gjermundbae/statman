"""Artikkelen som struktur, ikke som prosa.

En :class:`Article` er det en ferdig analyse har å si, satt opp slik at det kan
skrives ut i flere former uten å bli skrevet på nytt. Notatet i sakspakken og
den publiserte siden rendres begge herfra, så de kan ikke gli fra hverandre.

Modellen kjenner ikke til DuckDB, Polars eller matplotlib. Alt som kommer inn
er ferdig formatert tekst og ferdig valgte tall — publiseringslaget teller
ikke, summerer ikke og velger ikke utvalg, og kan derfor ikke velge feil. Det
er hele poenget med at det er et eget lag.

Ett unntak er skrevet ned og ikke sneket inn: en figur med :class:`Timeline`
lar leseren velge tidspunktet, og da finnes ikke svaret på forhånd. Der sier
analysen regelen — hvilken serie, hvilke grenser, hvor mange desimaler — og
sida bruker den. Se :class:`Layer` og ARCHITECTURE.md.

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
class Format:
    """Hvordan et tall skrives ut. Analysen bestemmer, sida gjentar.

    Feltet finnes fordi en figur med tidslinje ikke kan få avlesningene
    sine ferdig formatert: leseren velger tidspunktet, og de tallene er
    det for mange av til å skrives ut på forhånd. Da er alternativet at
    rendereren finner på en skrivemåte selv — og «0.6071904675213324»
    eller «60.72%» er begge feil for en norsk leser.

    Så presisjonen, fortegnet og enheten sies her, én gang per lag, og
    sida gjør nøyaktig det den får beskjed om. Det er fortsatt analysen
    som velger hvor mange desimaler et tall tåler.

    ``factor`` ganges på verdien før avrunding: 100 gjør en andel til
    prosent. ``sign`` setter pluss foran positive tall, som en endring
    skal ha og en beholdning ikke.
    """

    decimals: int = 0
    factor: float = 1.0
    suffix: str = ""
    sign: bool = False


@dataclass(frozen=True, slots=True)
class Timeline:
    """Skinna leseren kan dra i, og hvor håndtakene står når sida åpnes.

    ``labels`` er punktene, ferdig skrevet — «2016», «2017». Antallet
    dem er også seriens lengde: hvert merke skal ha én måling per punkt,
    i denne rekkefølgen.

    Punktene er *ikke* nødvendigvis alt kilden har. Ett punkt per år, i
    samme kvartal, er et valg tatt i analysen, og det er grunnen til at
    lista kommer ferdig hit i stedet for å utledes av seriene: en leser
    som kan stille inn to vilkårlige kvartaler kan lage en «endring» som
    i sin helhet er sesongsvingning.

    Det er to håndtak, ikke tre: ``to_point`` er det ene håndtaket i et
    punktlag *og* den høyre enden i et endringslag, og ``from_point`` er
    den venstre. Med bare ett tidspunkt å bære videre følger stillingen
    leseren har valgt med når hen bytter lag, i stedet for å sprette
    tilbake. Standardstillingen er et redaksjonelt valg — den er utsnittet
    saken faktisk argumenterer for.
    """

    labels: tuple[str, ...]
    label: str = ""
    note: str = ""
    from_point: int = 0
    to_point: int = 0


@dataclass(frozen=True, slots=True)
class Layer:
    """Ett fargelag i en figur som kan farges på flere måter.

    Et flisediagram har én oppdeling av flaten og mange måter å farge den
    på: lønn, kvinneandel, vekst, alder. Laget er den ene av dem, med
    tegnforklaringen som gjelder akkurat den.

    ``legend`` er ``(tone, tekst)`` og forklarer hva trinnene betyr *i dette
    laget* — «under 40 000 kr», ikke «skala1». Uten den er en ordnet skala
    bare fem farger.

    Resten av feltene gjelder bare figurer med :class:`Timeline`, og de er
    der fordi tidslinja flytter én ting inn i nettleseren: *hvilket* av
    lagets trinn en måling havner på, når leseren har valgt tidspunktet.
    Inndelinga selv står fortsatt her. ``edges`` er grensene mellom
    trinnene, i samme rekkefølge som ``legend``, og en skala med fem trinn
    har fire av dem.

    ``rule`` sier hva som måles: ``"point"`` leser serien i det ene
    punktet leseren står på, ``"change"`` regner endringen mellom de to.
    ``relative`` skiller de to måtene et endringslag kan lese den
    endringen på: sann er forholdet (``b / a - 1``, en prosentvekst), usann
    er differansen (``b - a``, prosentpoeng eller samme enhet som serien).
    En andel skal vanligvis ha differansen — «opp 3 prosentpoeng» sier noe
    en leser kan sjekke; «opp 12 prosent» av en andel er sant, men svarer
    ikke spørsmålet leseren stiller. Standarden er sann, fordi de første
    endringslagene i denne kodebasen alltid var forhold.
    ``floor`` er nedre grense for at en endring i det hele tatt skal
    vises — under et par hundre ansatte flytter én omorganisering
    prosenten mer enn arbeidsmarkedet gjør — og den prøves mot begge
    endene, siden hvilke yrker som er små endrer seg over tid. Et
    forholdslag trenger ofte en gulv av den grunnen; en differanse
    eksploderer ikke nær null og trenger sjeldnere en.

    ``span`` er ``(fra, til)`` inn i ``Timeline.labels`` og sier hvor
    langt laget rekker. Sykefraværet er årlig og ligger et år etter
    bestanden; da skal skinna vise det, ikke late som målingen finnes.

    ``missing_label`` og ``floor_label`` er ordene for de to måtene et tall
    kan mangle på, og de er to og ikke ett fordi de betyr forskjellige
    ting: «ikke publisert» er kilden som tier, «ikke sammenlignbar» er vi
    som lar være å regne. Begge skrives her — rendereren skal aldri finne
    på en formulering om hvorfor et tall mangler.
    """

    key: str
    label: str
    legend: tuple[tuple[str, str], ...] = ()
    caption: str = ""
    rule: str = ""
    relative: bool = True
    edges: tuple[float, ...] = ()
    format: Format | None = None
    level_label: str = ""
    level_format: Format | None = None
    floor: float | None = None
    span: tuple[int, int] = ()
    missing_label: str = ""
    floor_label: str = ""


@dataclass(frozen=True, slots=True)
class Mark:
    """Ett merke: en prikk i en sky, en strek i en stripe, en rad med søyler.

    ``values`` er det boblen viser, ferdig formatert. ``segments`` er
    ``(tone, verdi)`` for stablede søyler; positive ledd vokser høyre for
    null, negative venstre, slik at et negativt bidrag trekker totalen ned
    i stedet for å legge seg oppå.

    ``tones`` er én rolle per lag i en figur med :class:`Layer`-lag, i samme
    rekkefølge som lagene. ``tone`` gjelder når figuren ikke har lag.

    ``series`` erstatter ``tones`` i en figur med :class:`Timeline`: én
    målt serie per lag, i lagenes rekkefølge, med én verdi per punkt på
    tidslinja. ``None`` er et hull — ikke publisert i det punktet — og en
    **tom serie** betyr at merket ikke er målt i det laget i det hele
    tatt. De to er ikke det samme, og ingen av dem er en måling på null.
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
    points: tuple[tuple[float, float], ...] = ()
    point_labels: tuple[str, ...] = ()
    series: tuple[tuple[float | None, ...], ...] = ()


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
    timeline: Timeline | None = None

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


KINDS: tuple[str, ...] = ("scatter", "strip", "bars", "treemap", "line")

# Figurtyper som kan farges på flere måter. Lag på en figurtype som ikke står
# her ville blitt skrevet til fila og aldri tegnet — leseren hadde fått en
# velger som ikke gjorde noe.
KINDS_MED_LAG: tuple[str, ...] = ("treemap",)

# Figurtyper som kan ha tidslinje. Snevrere enn KINDS_MED_LAG med vilje:
# en tidslinje flytter *fargen* på en flate som ligger i ro. Skulle en
# rangert stripe følge den, måtte den sorteres og telles opp på nytt for
# hver stilling håndtaket står i, og opptelling er ikke rendererens jobb.
KINDS_MED_TID: tuple[str, ...] = ("treemap",)

# Hva et lag måler når tidslinja styrer det. «point» leser serien i det ene
# punktet, «change» regner endringen mellom de to.
RULES: tuple[str, ...] = ("point", "change")

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
    if chart.kind == "line":
        if chart.x is None or chart.y is None:
            feil.append(f"{hvor} er et linjediagram og trenger begge akser")
        # En linje gjennom ett punkt er et punkt. To er det minste som kan
        # vise en retning, og retning er hele grunnen til å bruke linje.
        korte = [m.label for m in chart.marks if len(m.points) < 2]
        if korte:
            feil.append(
                f"{hvor} har {len(korte)} linjer med færre enn to punkter "
                f"(f.eks. {korte[0]!r})"
            )
        skjeve = [
            m.label for m in chart.marks
            if m.point_labels and len(m.point_labels) != len(m.points)
        ]
        if skjeve:
            feil.append(
                f"{hvor} har linjer der punktteksten ikke følger punktene "
                f"(f.eks. {skjeve[0]!r})"
            )
    if chart.kind == "bars" and any(not m.segments for m in chart.marks):
        feil.append(f"{hvor} er et søylediagram, men har merker uten segmenter")
    if chart.picker and not chart.link:
        feil.append(f"{hvor} har en picker uten link, og styrer da ingenting")

    feil += _sjekk_lag(chart, hvor)

    feil += _sjekk_tidslinje(chart, hvor)

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
    #
    # Med tidslinje er det seriene som bærer fargen, og da er rollene
    # overflødige — 400 merker ganger sju lag er hundre kilobyte som ingen
    # leser. Sjekken flytter tilsvarende til _sjekk_tidslinje.
    if chart.timeline is None:
        ventet = len(chart.layers)
        mangler = [m.label for m in chart.marks if len(m.tones) != ventet]
        if mangler:
            feil.append(
                f"{hvor} har {ventet} fargelag, men {len(mangler)} merker oppgir "
                f"et annet antall roller (f.eks. {mangler[0]!r})"
            )
    return feil


def _sjekk_tidslinje(chart: Chart, hvor: str) -> list[str]:
    """Sjekkene på en tidslinje. Hver av dem skal kunne feile."""
    feil: list[str] = []
    tid = chart.timeline

    if tid is None:
        # Serier uten tidslinje har ingenting å være indeksert etter, og
        # ville blitt skrevet til fila og aldri lest.
        med_serie = [m.label for m in chart.marks if m.series]
        if med_serie:
            feil.append(
                f"{hvor} har {len(med_serie)} merker med serier, men ingen "
                f"tidslinje å lese dem langs (f.eks. {med_serie[0]!r})"
            )
        med_regel = [l.key for l in chart.layers if l.rule]
        if med_regel:
            feil.append(
                f"{hvor} har fargelag med regel ({med_regel[0]!r}), men ingen "
                "tidslinje å bruke den på"
            )
        return feil

    if chart.kind not in KINDS_MED_TID:
        feil.append(
            f"{hvor} har tidslinje, men {chart.kind!r} tegnes uten. "
            f"Typer med tidslinje: {', '.join(KINDS_MED_TID)}"
        )
    if not chart.layers:
        feil.append(f"{hvor} har tidslinje uten fargelag, og styrer da ingenting")

    n = len(tid.labels)
    # Ett punkt er ikke en tidslinje, det er et tidspunkt.
    if n < 2:
        feil.append(f"{hvor} har en tidslinje med {n} punkter, og trenger minst to")
        return feil

    for navn, i in (("from_point", tid.from_point), ("to_point", tid.to_point)):
        if not 0 <= i < n:
            feil.append(
                f"{hvor} har tidslinje der {navn} står på {i}, utenfor de {n} punktene"
            )
    if tid.from_point > tid.to_point:
        feil.append(
            f"{hvor} har en tidslinje som starter etter at den slutter "
            f"({tid.from_point} > {tid.to_point})"
        )

    for lag in chart.layers:
        hvem = f"{hvor}: fargelaget {lag.key!r}"
        if lag.rule not in RULES:
            feil.append(
                f"{hvem} har regelen {lag.rule!r}, som ikke finnes. "
                f"Kjente: {', '.join(RULES)}"
            )
        if not lag.edges:
            feil.append(f"{hvem} har ingen grenser, og kan da ikke velge et trinn")
        elif len(lag.legend) not in (len(lag.edges) + 1, len(lag.edges) + 2):
            # Tegnforklaringen *er* skalaen: de første postene er trinnene i
            # rekkefølge, og en post til på slutten er hullet. Stemmer ikke
            # antallet, viser figuren og forklaringen hver sin inndeling.
            feil.append(
                f"{hvem} har {len(lag.edges)} grenser og {len(lag.legend)} poster i "
                f"tegnforklaringen — ventet {len(lag.edges) + 1} trinn, "
                "eventuelt ett til for hullet"
            )
        elif len(lag.legend) == len(lag.edges) + 2 and lag.legend[-1][0] != TONE_MANGLER:
            feil.append(
                f"{hvem} har en post for mye i tegnforklaringen, og den siste er "
                f"ikke {TONE_MANGLER!r}"
            )
        if list(lag.edges) != sorted(lag.edges):
            feil.append(f"{hvem} har grenser som ikke stiger")
        if lag.format is None:
            feil.append(f"{hvem} sier ikke hvordan tallet skal skrives")
        if lag.floor is not None and lag.rule != "change":
            feil.append(f"{hvem} har en nedre grense, men måler ikke en endring")
        if not lag.missing_label:
            feil.append(f"{hvem} sier ikke hva som skal stå der målingen mangler")
        if lag.floor is not None and not lag.floor_label:
            feil.append(f"{hvem} har en nedre grense, men ikke et ord for å ligge under den")
        if lag.floor_label and lag.floor is None:
            feil.append(f"{hvem} har et ord for å ligge under en grense den ikke har")
        if bool(lag.level_label) != bool(lag.level_format):
            feil.append(f"{hvem} oppgir nivået med bare halvparten av det som trengs")
        if lag.span:
            if len(lag.span) != 2:
                feil.append(f"{hvem} har en rekkevidde som ikke er (fra, til)")
            elif not (0 <= lag.span[0] <= lag.span[1] < n):
                feil.append(
                    f"{hvem} rekker fra {lag.span[0]} til {lag.span[1]}, "
                    f"utenfor de {n} punktene"
                )

    # En serie som ikke følger punktene ville lest en måling av et annet år.
    # Tom serie er tillatt og betyr noe eget — se Mark.series.
    ventet = len(chart.layers)
    skjeve = [m.label for m in chart.marks if len(m.series) != ventet]
    if skjeve:
        feil.append(
            f"{hvor} har {ventet} fargelag, men {len(skjeve)} merker oppgir et "
            f"annet antall serier (f.eks. {skjeve[0]!r})"
        )
    korte = [
        (m.label, i)
        for m in chart.marks
        for i, serie in enumerate(m.series)
        if serie and len(serie) != n
    ]
    if korte:
        feil.append(
            f"{hvor} har {len(korte)} serier med et annet antall målinger enn "
            f"tidslinjas {n} punkter (f.eks. {korte[0][0]!r} i lag {korte[0][1]})"
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
_KOMPAKTE: tuple[type, ...] = (Axis, Readout, Guide, Mark, Layer, Format, Timeline)


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
            points=tuple((float(x), float(y)) for x, y in rå.get("points") or ()),
            point_labels=tuple(str(t) for t in rå.get("point_labels") or ()),
            series=tuple(
                tuple(None if v is None else float(v) for v in serie)
                for serie in rå.get("series") or ()
            ),
        )

    def formatering(rå: Any) -> Format | None:
        # `is None`, ikke `not rå`: et format der alt står på standardverdi
        # skrives kompakt som `{}`, og det er et format — ikke fraværet av ett.
        if rå is None:
            return None
        return Format(
            decimals=int(rå.get("decimals", 0)),
            factor=float(rå.get("factor", 1.0)),
            suffix=str(rå.get("suffix", "")),
            sign=bool(rå.get("sign", False)),
        )

    def lag(rå: dict[str, Any]) -> Layer:
        grense = rå.get("floor")
        return Layer(
            key=str(rå.get("key", "")),
            label=str(rå.get("label", "")),
            legend=tuple((str(t), str(s)) for t, s in rå.get("legend") or ()),
            caption=str(rå.get("caption", "")),
            rule=str(rå.get("rule", "")),
            relative=bool(rå.get("relative", True)),
            edges=tuple(float(e) for e in rå.get("edges") or ()),
            format=formatering(rå.get("format")),
            level_label=str(rå.get("level_label", "")),
            level_format=formatering(rå.get("level_format")),
            floor=None if grense is None else float(grense),
            span=tuple(int(i) for i in rå.get("span") or ()),  # type: ignore[arg-type]
            missing_label=str(rå.get("missing_label", "")),
            floor_label=str(rå.get("floor_label", "")),
        )

    def tidslinje(rå: Any) -> Timeline | None:
        if rå is None:
            return None
        return Timeline(
            labels=tuple(str(t) for t in rå.get("labels") or ()),
            label=str(rå.get("label", "")),
            note=str(rå.get("note", "")),
            from_point=int(rå.get("from_point", 0)),
            to_point=int(rå.get("to_point", 0)),
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
        timeline=tidslinje(data.get("timeline")),
    )


def _tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuples(v) for v in value)
    return value
