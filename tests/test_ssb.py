"""Tester for SSB-konnektoren.

De rene funksjonene testes offline. Testene som faktisk snakker med SSB er
merket ``network`` og hoppes over som standard:

    uv run pytest -m network
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from statman import io
from statman.http import RateLimiter
from statman.sources import ssb


# --------------------------------------------------------------------------
# Rene funksjoner
# --------------------------------------------------------------------------
def test_data_params_defaults() -> None:
    assert ssb.data_params() == {"lang": "no", "format": "json-stat2"}


def test_data_params_single_and_list_codes() -> None:
    params = ssb.data_params({"Tid": "TOP(12)", "Region": ["0301", "1103"]})
    assert params["valueCodes[Tid]"] == "TOP(12)"
    assert params["valueCodes[Region]"] == "0301,1103"


def test_data_params_respects_lang_and_format() -> None:
    params = ssb.data_params(lang="en", fmt="csv")
    assert params["lang"] == "en"
    assert params["format"] == "csv"


def test_data_params_takes_codelists() -> None:
    params = ssb.data_params({"Region": "*"}, codelists={"Region": "agg_KommSummerHist"})
    assert params["codelist[Region]"] == "agg_KommSummerHist"
    assert params["valueCodes[Region]"] == "*"


def test_urls_use_given_base() -> None:
    base = "https://example.test/api/v2"
    assert ssb.data_url("03013", base) == "https://example.test/api/v2/tables/03013/data"
    assert ssb.metadata_url("03013", base) == "https://example.test/api/v2/tables/03013/metadata"


def test_base_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ssb.BASE_ENV, "https://example.test/api/v2/")
    assert ssb.base_url() == "https://example.test/api/v2"
    assert ssb.data_url("03013").startswith("https://example.test/api/v2/tables/03013")


def test_base_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ssb.BASE_ENV, raising=False)
    monkeypatch.setattr(ssb, "_resolved_base", None)
    assert ssb.base_url() == ssb.BASE_CANDIDATES[0]


def test_count_cells_from_json_stat2() -> None:
    payload = json.dumps({"class": "dataset", "size": [3, 4, 2]}).encode()
    assert ssb.count_cells(payload) == 24


def test_count_cells_on_garbage_is_negative() -> None:
    assert ssb.count_cells(b"ikke json") == -1
    assert ssb.count_cells(b"{}") == -1


# --------------------------------------------------------------------------
# Throttle
# --------------------------------------------------------------------------
class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_rate_limiter_allows_burst_then_waits() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(max_calls=3, per_seconds=10.0)

    for _ in range(3):
        assert limiter.acquire(_sleep=clock.sleep, _now=clock.now) == 0.0
    waited = limiter.acquire(_sleep=clock.sleep, _now=clock.now)

    assert waited > 0
    assert clock.t >= 10.0


def test_rate_limiter_window_slides() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(max_calls=2, per_seconds=10.0)
    limiter.acquire(_sleep=clock.sleep, _now=clock.now)
    limiter.acquire(_sleep=clock.sleep, _now=clock.now)

    clock.t += 11.0  # vinduet har rullet forbi
    assert limiter.acquire(_sleep=clock.sleep, _now=clock.now) == 0.0


def test_ssb_limiter_is_under_documented_ceiling() -> None:
    # SSB tillater 30 kall per 10 sekunder.
    assert ssb.LIMITER.max_calls <= 30
    assert ssb.LIMITER.per_seconds >= 10.0


# --------------------------------------------------------------------------
# Ekte nettverk
# --------------------------------------------------------------------------
@pytest.mark.network
def test_probe_finds_working_base() -> None:
    result = ssb.probe()
    assert result["working"], f"Ingen basis-URL svarte: {result['tried']}"


@pytest.mark.network
def test_fetch_kpi_writes_raw_with_provenance(project: Path) -> None:
    """Henter faktisk KPI (tabell 03013) fra SSB og verifiserer rålaget."""
    ssb.probe()
    version = ssb.fetch_table(
        "03013",
        value_codes={"Konsumgrp": "TOTAL", "ContentsCode": "KpiIndMnd", "Tid": "TOP(6)"},
    )

    meta = io.read_meta(version)
    assert meta["http_status"] == 200
    assert meta["bytes"] > 0
    assert meta["cells"] > 0
    assert "ssb" in meta["endpoint"]

    doc = json.loads(io.raw_latest("ssb", "03013").read_text(encoding="utf-8"))
    assert doc["class"] == "dataset"
    assert len(doc["value"]) >= 1


@pytest.mark.network
def test_kommune_codelist_still_covers_every_municipality(project: Path) -> None:
    """Hele befolkningskjeden hviler på denne kodelista.

    Endrer SSB navn på den, eller legger til en «Kommuner 2027»-inndeling,
    skal vi få vite det her og ikke via en graf med feil tall i.
    """
    import re

    ssb.probe()
    doc = ssb.fetch_codelist("agg_KommSummerHist")
    koder = [v["code"] for v in doc["values"]]
    kommuner = [k for k in koder if re.fullmatch(r"K_\d{4}", k)]

    assert doc["type"] == "Aggregation"
    assert "2024" in doc["label"]
    assert len(kommuner) == 357, f"Antall kommuner endret seg: {len(kommuner)}"


@pytest.mark.network
def test_fetch_befolkning_with_codelist(project: Path) -> None:
    """Henter faktisk 06913 med aggregert kodeliste og dekoder svaret."""
    from statman import jsonstat

    ssb.probe()
    version = ssb.fetch_table(
        "06913",
        value_codes={"Region": "*", "ContentsCode": "Folkemengde", "Tid": "TOP(2)"},
        codelists={"Region": "agg_KommSummerHist"},
        dataset="06913_kommune",
    )

    meta = io.read_meta(version)
    assert meta["http_status"] == 200
    assert meta["table_id"] == "06913"
    assert meta["params"]["codelist[Region]"] == "agg_KommSummerHist"

    df = jsonstat.to_frame(io.raw_latest("ssb", "06913_kommune"))
    assert df.height == meta["cells"]
    # SSB oppgir flerspråklige navn ("Oslo - Oslove"), så vi sjekker prefikset.
    assert df.filter(pl.col("region") == "K_0301")["region_label"][0].startswith("Oslo")


@pytest.mark.network
def test_fetch_metadata(project: Path) -> None:
    ssb.probe()
    version = ssb.fetch_metadata("03013")
    doc = json.loads(io.raw_latest("ssb", "03013__metadata").read_text(encoding="utf-8"))
    assert io.read_meta(version)["kind"] == "metadata"
    assert doc  # metadata-strukturen varierer; her sjekker vi bare at noe kom
