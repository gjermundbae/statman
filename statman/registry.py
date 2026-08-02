"""@model-dekoratøren, byggegrafen og kjøreren.

En modell er en Python-funksjon som tar en :class:`Context` og returnerer noe
tabellaktig. Kjøreren sorterer modellene topologisk, kjører dem, kontrollerer
resultatet og materialiserer det til Parquet.

Modellkontrakten
----------------

* Navnet er ``"<lag>.<tabell>"``, der laget er ``clean`` eller ``mart``.
* Returverdien kan være en DuckDB-relasjon, en Polars- eller pandas-DataFrame
  eller en Arrow-tabell. Kjøreren skriver Parquet uansett.
* ``deps`` er andre modellnavn, eller rådata med ``raw:``-prefiks. Modeller
  inngår i grafen; rådata er inndata og kontrolleres før bygget starter.
* Modellavhengigheter registreres som views før funksjonen kalles. Viewnavnet
  er modellnavnet med punktum byttet mot understrek — ``clean.kpi`` blir
  ``clean_kpi``. :meth:`Context.ref` gjør det samme eksplisitt.
* ``ctx.raw_latest(ref)`` gir stien til nyeste henting og noterer hvilken
  versjon den landet på; ``ctx.read_raw(ref)`` leser den rett inn som relasjon.
  ``ctx.register(navn, df)`` gjør en DataFrame tilgjengelig for SQL, for kilder
  som må dekodes i Python først.

Sjekker
-------

``checks`` kjøres mot resultatet før det får sitt endelige navn. En feilet
sjekk stopper bygget *og* etterlater ingen fil, så en tidligere gyldig tabell
blir stående og ingen nedstrøms modell kan lese underkjente tall.

===============================  ==========================================
``unique:kolonne[,kolonne2]``    kombinasjonen må være unik
``not_null:kolonne``             ingen nullverdier
alt annet                        SQL-uttrykk som må være sant for hver rad
                                 (null teller som brudd)
===============================  ==========================================

Byggelogg
---------

Hver bygget tabell får en ``<tabell>.build.json`` ved siden av seg med
tidspunkt, radtall, sjekkene som passerte, og de oppløste råversjonene den
hviler på — arvet oppstrøms, så en mart-tabell kan spores til kilden uten å
følge kjeden manuelt. Les den med :func:`statman.io.read_manifest`.
"""

from __future__ import annotations

import importlib
import pkgutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

from statman import io

if TYPE_CHECKING:  # pragma: no cover - kun for typehinting
    import duckdb

RAW_PREFIX = "raw:"
MODELS_PACKAGE = "statman.models"

ModelFn = Callable[["Context"], Any]

_REGISTRY: dict[str, "Model"] = {}
_discovered = False


class CheckFailed(RuntimeError):
    """En modell brøt en av sine egne sjekker. Resultatet ble ikke lagret."""


class MissingRawData(FileNotFoundError):
    """Byggeplanen trenger rådata som ikke er hentet."""


@dataclass(frozen=True, slots=True)
class Model:
    name: str
    fn: ModelFn
    deps: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    doc: str = ""

    @property
    def model_deps(self) -> tuple[str, ...]:
        return tuple(d for d in self.deps if not d.startswith(RAW_PREFIX))

    @property
    def raw_deps(self) -> tuple[str, ...]:
        return tuple(d.removeprefix(RAW_PREFIX) for d in self.deps if d.startswith(RAW_PREFIX))


@dataclass(frozen=True, slots=True)
class BuildResult:
    name: str
    path: Path
    rows: int
    seconds: float


# --------------------------------------------------------------------------
# Registrering
# --------------------------------------------------------------------------
def model(
    *,
    name: str,
    deps: Sequence[str] = (),
    checks: Sequence[str] = (),
    doc: str = "",
) -> Callable[[ModelFn], ModelFn]:
    """Registrer en funksjon som modell.

    ``name`` må være ``"<lag>.<tabell>"``. ``deps`` er andre modellnavn eller
    ``"raw:<kilde>/<datasett>"``. ``checks`` kjøres mot resultatet; se
    :func:`run_checks` for formatene.
    """

    def decorator(fn: ModelFn) -> ModelFn:
        io.split_model_name(name)  # validerer lag og form
        if name in _REGISTRY and _REGISTRY[name].fn is not fn:
            raise ValueError(f"Modellen {name!r} er allerede registrert")
        _REGISTRY[name] = Model(
            name=name,
            fn=fn,
            deps=tuple(deps),
            checks=tuple(checks),
            doc=doc or _first_line(fn.__doc__),
        )
        return fn

    return decorator


def _first_line(text: str | None) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def split_raw_ref(ref: str) -> tuple[str, str]:
    """``"ssb/06913_kommune"`` -> ``("ssb", "06913_kommune")``."""
    source, sep, dataset = ref.partition("/")
    if not sep or not dataset:
        raise ValueError(f"Rå-referanse må være '<kilde>/<datasett>', fikk {ref!r}")
    return source, dataset


def registry() -> dict[str, Model]:
    """Alle registrerte modeller (etter at :func:`discover` har kjørt)."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Kun for tester."""
    global _discovered
    _REGISTRY.clear()
    _discovered = False


def discover(package: str = MODELS_PACKAGE, *, force: bool = False) -> None:
    """Importer alle modulene i modellpakka så dekoratørene kjører."""
    global _discovered
    if _discovered and not force:
        return
    pkg = importlib.import_module(package)
    for info in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{package}.{info.name}")
    _discovered = True


# --------------------------------------------------------------------------
# Kontekst
# --------------------------------------------------------------------------
class Context:
    """Det en modellfunksjon får utdelt."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con
        # Hvilken råversjon hver ``raw_latest``/``read_raw`` faktisk landet
        # på. Kjøreren tømmer denne per modell og skriver den til
        # byggeloggen, så proveniensen følger tallene og ikke må slås opp
        # på nytt senere — da kan svaret ha blitt et annet.
        self.raw_brukt: dict[str, Path] = {}

    @staticmethod
    def view_name(model_name: str) -> str:
        """``"clean.kpi"`` -> ``"clean_kpi"`` — navnet du bruker i SQL."""
        return model_name.replace(".", "_")

    def sql(self, query: str) -> duckdb.DuckDBPyRelation:
        return self.con.sql(query)

    def ref(self, name: str) -> duckdb.DuckDBPyRelation:
        """Registrer en ferdig bygget modell som view og returner relasjonen."""
        path = io.model_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Avhengigheten {name} er ikke bygget ({path})")
        view = self.view_name(name)
        self.con.execute(
            f"create or replace view {view} as "
            f"select * from read_parquet('{path.as_posix()}')"
        )
        return self.con.table(view)

    def register(self, name: str, obj: Any) -> duckdb.DuckDBPyRelation:
        """Gjør en DataFrame tilgjengelig for SQL under ``name``.

        For kilder som må dekodes i Python før SQL kan brukes — json-stat2 er
        den typiske. Alternativet, å la DuckDB plukke opp lokale variabler,
        virker men avhenger av hvilken stakkramme kallet skjer i.
        """
        self.con.register(name, obj)
        return self.con.table(name)

    def raw_latest(self, ref: str) -> Path:
        """``ctx.raw_latest("ssb/03013")`` -> sti til nyeste rådatafil.

        Noterer samtidig hvilken versjon som ble valgt, for byggeloggen.
        """
        version = io.raw_latest_dir(*split_raw_ref(ref))
        self.raw_brukt[ref] = version
        return io.raw_data_file(version)

    def read_raw(self, ref: str) -> duckdb.DuckDBPyRelation:
        """Les nyeste rådatafil som relasjon. Velger leser ut fra filendelsen."""
        path = self.raw_latest(ref)
        posix = path.as_posix()
        if path.suffix in {".csv", ".tsv"}:
            return self.con.sql(f"select * from read_csv_auto('{posix}')")
        return self.con.sql(f"select * from read_json_auto('{posix}')")


# --------------------------------------------------------------------------
# Graf
# --------------------------------------------------------------------------
def build_order(targets: Sequence[str] | None = None) -> list[str]:
    """Topologisk rekkefølge for målene og alt oppstrøms.

    Reiser ``KeyError`` ved ukjent modell og ``ValueError`` ved sykel.
    """
    roots = list(targets) if targets else sorted(_REGISTRY)
    for name in roots:
        if name not in _REGISTRY:
            raise KeyError(f"Ukjent modell {name!r}")

    order: list[str] = []
    permanent: set[str] = set()
    temporary: set[str] = set()

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if name in permanent:
            return
        if name in temporary:
            cycle = " -> ".join([*trail, name])
            raise ValueError(f"Sykel i modellgrafen: {cycle}")
        if name not in _REGISTRY:
            raise KeyError(f"Ukjent avhengighet {name!r} (referert fra {trail[-1]!r})")
        temporary.add(name)
        for dep in _REGISTRY[name].model_deps:
            visit(dep, (*trail, name))
        temporary.discard(name)
        permanent.add(name)
        order.append(name)

    for name in roots:
        visit(name, ())
    return order


# --------------------------------------------------------------------------
# Råavhengigheter
# --------------------------------------------------------------------------
def missing_raw(names: Sequence[str]) -> dict[str, list[str]]:
    """Råreferanser i byggeplanen som ikke finnes, med modellene som vil ha dem."""
    mangler: dict[str, list[str]] = {}
    for name in names:
        for ref in _REGISTRY[name].raw_deps:
            if not io.raw_versions(*split_raw_ref(ref)):
                mangler.setdefault(ref, []).append(name)
    return mangler


def require_raw(names: Sequence[str]) -> None:
    """Stopp før første modell kjører hvis rådata mangler.

    Uten dette dør bygget først halvveis uti rekkefølgen, med en
    ``FileNotFoundError`` kastet inne fra en modellfunksjon, og sier bare
    fra om det første datasettet som manglet.
    """
    mangler = missing_raw(names)
    if not mangler:
        return

    linjer = [f"Mangler rådata for {len(mangler)} datasett:"]
    for ref, modeller in sorted(mangler.items()):
        linjer.append(f"  {ref:<28} trengs av {', '.join(sorted(modeller))}")
        source, dataset = split_raw_ref(ref)
        naboer = sorted(p.name for p in (io.raw_dir() / source).glob("*") if p.is_dir())
        if naboer and dataset not in naboer:
            linjer.append(f"  {'':<28} fant derimot under {source}/: {', '.join(naboer)}")
    linjer.append("Kjør ingest for kildene først.")
    raise MissingRawData("\n".join(linjer))


# --------------------------------------------------------------------------
# Sjekker
# --------------------------------------------------------------------------
def run_checks(
    con: duckdb.DuckDBPyConnection, name: str, path: Path, checks: Sequence[str]
) -> None:
    """Kjør sjekkene til en modell mot den ferdigskrevne Parquet-fila.

    Tre former:

    * ``"unique:kolonne[,kolonne2]"`` — kombinasjonen må være unik
    * ``"not_null:kolonne"`` — ingen nullverdier
    * alt annet — SQL-uttrykk som må være sant for hver rad
    """
    if not checks:
        return
    src = f"read_parquet('{path.as_posix()}')"
    for check in checks:
        if check.startswith("unique:"):
            cols = ", ".join(c.strip() for c in check.removeprefix("unique:").split(","))
            query = (
                f"select (select count(*) from {src}) "
                f"- (select count(*) from (select distinct {cols} from {src}))"
            )
        elif check.startswith("not_null:"):
            col = check.removeprefix("not_null:").strip()
            query = f"select count(*) from {src} where {col} is null"
        else:
            query = f"select count(*) from {src} where not coalesce(({check}), false)"

        row = con.execute(query).fetchone()
        violations = int(row[0]) if row and row[0] is not None else 0
        if violations:
            raise CheckFailed(f"{name}: sjekken {check!r} feilet for {violations} rader")


# --------------------------------------------------------------------------
# Kjøring
# --------------------------------------------------------------------------
def build(
    targets: Sequence[str] | None = None,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> list[BuildResult]:
    """Bygg modellene (og alt de avhenger av) i riktig rekkefølge."""
    discover()
    order = build_order(targets)
    require_raw(order)

    owns_connection = con is None
    con = con or io.connect()
    ctx = Context(con)
    results: list[BuildResult] = []
    # Råversjonene hver modell hviler på, inkludert dem den arver oppstrøms.
    # Byggerekkefølgen er topologisk, så oppstrøms er alltid fylt ut først.
    raw_per_modell: dict[str, dict[str, Path]] = {}
    try:
        for name in order:
            spec = _REGISTRY[name]
            for dep in spec.model_deps:
                ctx.ref(dep)

            started = time.perf_counter()
            ctx.raw_brukt = {}
            table = spec.fn(ctx)
            if table is None:
                raise TypeError(f"Modellen {name} returnerte None")

            # Sjekkene kjøres mot en midlertidig fil. Først når de har
            # passert, får den det endelige navnet. Ellers ville en feilet
            # sjekk stoppet bygget, men latt de underkjente tallene ligge
            # igjen på disk der neste modell ville lest dem som gyldige.
            path = io.model_path(name)
            staged = io.staging_path(path)
            try:
                rows = io.write_table(table, staged)
                run_checks(con, name, staged, spec.checks)
                staged.replace(path)
            except BaseException:
                staged.unlink(missing_ok=True)
                raise

            raw_per_modell[name] = dict(ctx.raw_brukt)
            for dep in spec.model_deps:
                raw_per_modell[name].update(raw_per_modell.get(dep, {}))

            seconds = time.perf_counter() - started
            io.write_manifest(
                name,
                _manifest(name, spec, rows, seconds, raw_per_modell[name]),
            )
            results.append(BuildResult(name=name, path=path, rows=rows, seconds=seconds))
    finally:
        if owns_connection:
            con.close()
    return results


def _manifest(
    name: str, spec: Model, rows: int, seconds: float, raw_brukt: dict[str, Path]
) -> dict[str, Any]:
    """Byggeloggen: hva som ble bygget, når, og fra nøyaktig hvilke rådata."""
    raw: dict[str, Any] = {}
    for ref, version in sorted(raw_brukt.items()):
        raw[ref] = {"version": version.name, **io.read_meta(version)}
    return {
        "model": name,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "seconds": round(seconds, 4),
        "checks": list(spec.checks),
        "model_deps": list(spec.model_deps),
        "raw": raw,
    }
