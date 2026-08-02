from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from statman import io


def test_project_root_honors_env(project: Path) -> None:
    assert io.project_root() == project.resolve()
    assert io.data_dir() == project / "data"
    assert io.raw_dir() == project / "data" / "raw"
    assert io.output_dir() == project / "output"


def test_split_model_name_ok() -> None:
    assert io.split_model_name("mart.kpi_monthly") == ("mart", "kpi_monthly")
    assert io.split_model_name("clean.a.b") == ("clean", "a.b")


@pytest.mark.parametrize("bad", ["kpi_monthly", "raw.kpi", "mart.", ".kpi"])
def test_split_model_name_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError):
        io.split_model_name(bad)


def test_model_path(project: Path) -> None:
    assert io.model_path("mart.kpi") == project / "data" / "mart" / "kpi.parquet"


def test_write_raw_records_provenance(project: Path) -> None:
    payload = b'[{"a": 1}]'
    version = io.write_raw("ssb", "03013", payload, {"endpoint": "https://x", "license": "NLOD"})

    assert (version / "data.json").read_bytes() == payload
    meta = json.loads((version / "_meta.json").read_text(encoding="utf-8"))
    assert meta["sha256"] == hashlib.sha256(payload).hexdigest()
    assert meta["bytes"] == len(payload)
    assert meta["source"] == "ssb"
    assert meta["dataset"] == "03013"
    assert meta["endpoint"] == "https://x"
    assert meta["license"] == "NLOD"
    assert "fetched_at" in meta


def test_write_raw_never_overwrites(project: Path) -> None:
    first = io.write_raw("ssb", "03013", b"1")
    second = io.write_raw("ssb", "03013", b"2")

    assert first != second
    assert first.exists() and second.exists()
    assert (first / "data.json").read_bytes() == b"1"
    assert len(io.raw_versions("ssb", "03013")) == 2


def test_raw_latest_picks_newest(project: Path) -> None:
    io.write_raw("ssb", "03013", b"gammel")
    newest = io.write_raw("ssb", "03013", b"ny")

    assert io.raw_latest_dir("ssb", "03013") == newest
    assert io.raw_latest("ssb", "03013").read_bytes() == b"ny"


def test_raw_latest_missing_is_explicit(project: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Ingen rådata"):
        io.raw_latest("ssb", "finnes_ikke")


def test_write_raw_respects_suffix(project: Path) -> None:
    version = io.write_raw("x", "y", b"a,b\n1,2\n", suffix="csv")
    assert (version / "data.csv").exists()
    assert io.raw_latest("x", "y").suffix == ".csv"


def test_write_table_and_load_roundtrip(project: Path) -> None:
    import polars as pl

    frame = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    path = io.model_path("clean.demo")
    rows = io.write_table(frame, path)

    assert rows == 3
    assert path.exists()
    back = io.load("clean.demo")
    assert back.to_dicts() == frame.to_dicts()


def test_write_table_accepts_duckdb_relation(project: Path) -> None:
    con = io.connect()
    try:
        rel = con.sql("select * from (values (1), (2)) as t(n)")
        rows = io.write_table(rel, io.model_path("clean.rel"))
    finally:
        con.close()
    assert rows == 2
    assert sorted(io.load("clean.rel")["n"].to_list()) == [1, 2]


def test_write_table_rejects_unknown_type(project: Path) -> None:
    with pytest.raises(TypeError):
        io.write_table(object(), io.model_path("clean.nope"))


def test_load_unbuilt_model_is_explicit(project: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ikke bygget"):
        io.load("mart.finnes_ikke")
