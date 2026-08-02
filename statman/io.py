"""Stier, proveniens og lagring.

Dette laget vet hvor ting ligger og hvordan de skrives. Det inneholder
ingen forretningslogikk, og det tolker aldri innholdet i et API-svar.

Prosjektroten kan overstyres med miljøvariabelen ``STATMAN_ROOT``. Alle stier
er funksjoner (ikke modulkonstanter) nettopp for at testene skal kunne peke
roten mot en midlertidig mappe.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - kun for typehinting
    import duckdb
    import polars as pl

LAYERS: Final[tuple[str, ...]] = ("clean", "mart")
ROOT_ENV: Final[str] = "STATMAN_ROOT"
_TS_FMT: Final[str] = "%Y-%m-%dT%H%M%SZ"


# --------------------------------------------------------------------------
# Stier
# --------------------------------------------------------------------------
def project_root() -> Path:
    """Prosjektroten. Overstyres med ``STATMAN_ROOT``."""
    override = os.environ.get(ROOT_ENV)
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return project_root() / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def layer_dir(layer: str) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Ukjent lag {layer!r}. Gyldige: {', '.join(LAYERS)}")
    return data_dir() / layer


def output_dir() -> Path:
    return project_root() / "output"


def catalog_path() -> Path:
    return project_root() / "catalog" / "metrics.yml"


def split_model_name(name: str) -> tuple[str, str]:
    """``"mart.kpi_monthly"`` -> ``("mart", "kpi_monthly")``."""
    layer, sep, table = name.partition(".")
    if not sep or not table:
        raise ValueError(f"Modellnavn må være '<lag>.<tabell>', fikk {name!r}")
    if layer not in LAYERS:
        raise ValueError(f"Ukjent lag {layer!r} i {name!r}. Gyldige: {', '.join(LAYERS)}")
    return layer, table


def model_path(name: str) -> Path:
    """Parquet-stien en modell materialiseres til."""
    layer, table = split_model_name(name)
    return layer_dir(layer) / f"{table}.parquet"


def staging_path(path: Path) -> Path:
    """Midlertidig nabofil til ``path``.

    Samme mappe, så byttet til slutt blir en atomisk omdøping og ikke en
    kopiering mellom filsystemer. Navnet starter med punktum, så en rest
    etter en avbrutt kjøring ikke ser ut som en ferdig tabell.
    """
    return path.with_name(f".{path.name}.ny")


def manifest_path(name: str) -> Path:
    """Byggeloggen som ligger ved siden av en modells parquet."""
    layer, table = split_model_name(name)
    return layer_dir(layer) / f"{table}.build.json"


# --------------------------------------------------------------------------
# Rålaget — uforanderlig, med proveniens
# --------------------------------------------------------------------------
def write_raw(
    source: str,
    dataset: str,
    payload: bytes,
    meta: dict[str, Any] | None = None,
    *,
    suffix: str = "json",
) -> Path:
    """Skriv et API-svar uendret til en ny tidsstemplet versjonsmappe.

    Returnerer mappa, som inneholder ``data.<suffix>`` og ``_meta.json``.
    Eksisterende versjoner røres aldri.
    """
    stamp = datetime.now(timezone.utc).strftime(_TS_FMT)
    parent = raw_dir() / source / dataset
    version = parent / stamp
    counter = 1
    while version.exists():
        version = parent / f"{stamp}-{counter}"
        counter += 1
    version.mkdir(parents=True)

    (version / f"data.{suffix}").write_bytes(payload)
    full_meta: dict[str, Any] = {
        "source": source,
        "dataset": dataset,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "suffix": suffix,
        **(meta or {}),
    }
    (version / "_meta.json").write_text(
        json.dumps(full_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return version


def raw_versions(source: str, dataset: str) -> list[Path]:
    """Alle versjonsmapper for et datasett, eldst først."""
    parent = raw_dir() / source / dataset
    if not parent.is_dir():
        return []
    return sorted((p for p in parent.iterdir() if p.is_dir()), key=lambda p: p.name)


def raw_latest_dir(source: str, dataset: str) -> Path:
    versions = raw_versions(source, dataset)
    if not versions:
        raise FileNotFoundError(
            f"Ingen rådata for {source}/{dataset}. Kjør ingest for kilden først."
        )
    return versions[-1]


def raw_data_file(version_dir: Path) -> Path:
    matches = sorted(version_dir.glob("data.*"))
    if not matches:
        raise FileNotFoundError(f"Fant ingen data-fil i {version_dir}")
    return matches[0]


def raw_latest(source: str, dataset: str) -> Path:
    """Sti til datafila i nyeste versjon av et rådatasett."""
    return raw_data_file(raw_latest_dir(source, dataset))


def raw_version_dir(ref: str, version: str) -> Path:
    """``("ssb/06913_kommune", "2026-08-02T220830Z")`` -> versjonsmappa.

    Motstykket til det byggeloggen skriver ned. Lagrer vi tidsstempelet og
    ikke en absolutt sti, kan prosjektet flyttes uten at proveniensen
    peker i tomme luften.
    """
    return raw_dir() / ref / version


def read_meta(version_dir: Path) -> dict[str, Any]:
    return json.loads((version_dir / "_meta.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Byggelogg
# --------------------------------------------------------------------------
def write_manifest(name: str, payload: dict[str, Any]) -> Path:
    """Skriv byggeloggen for en modell."""
    path = manifest_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_manifest(name: str) -> dict[str, Any]:
    """Byggeloggen for en modell: når den ble bygget, og fra hvilke rådata.

    Dette er svaret på «hvilken henting ga dette tallet». Les den her i
    stedet for å slå opp nyeste rådata på nytt — nyeste kan ha blitt en
    annen siden modellen ble bygget.
    """
    path = manifest_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"Ingen byggelogg for {name} ({path}). Bygg modellen med `statman build {name}`."
        )
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Motor og materialisering
# --------------------------------------------------------------------------
def connect() -> duckdb.DuckDBPyConnection:
    """Ny in-memory DuckDB-sesjon. Importeres lazy så resten kan testes uten."""
    import duckdb

    return duckdb.connect()


def write_table(obj: Any, path: Path) -> int:
    """Skriv en tabell til Parquet og returner antall rader.

    Tar imot DuckDB-relasjon, Polars-/pandas-DataFrame eller Arrow-tabell.
    """
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    target = str(path)

    if hasattr(obj, "write_parquet"):  # DuckDB-relasjon eller Polars
        obj.write_parquet(target)
    elif hasattr(obj, "to_parquet"):  # pandas
        obj.to_parquet(target, index=False)
    elif hasattr(obj, "num_rows"):  # Arrow
        pq.write_table(obj, target)
    else:
        raise TypeError(
            f"Vet ikke hvordan {type(obj).__name__} skrives til Parquet. "
            "Returner en DuckDB-relasjon, Polars/pandas-DataFrame eller Arrow-tabell."
        )
    return int(pq.ParquetFile(target).metadata.num_rows)


def load(name: str) -> pl.DataFrame:
    """Les en ferdig bygget modell som Polars-DataFrame."""
    import polars as pl

    path = model_path(name)
    if not path.exists():
        raise FileNotFoundError(f"{name} er ikke bygget ennå ({path}). Kjør `statman build`.")
    return pl.read_parquet(path)
