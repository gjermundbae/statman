"""Tester for Norges Bank-konnektoren.

De rene delene (URL og parametre) testes offline. Testen som faktisk
snakker med Norges Bank er merket ``network`` og hoppes over som standard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from statman import io
from statman.sources import norges_bank


# --------------------------------------------------------------------------
# Rene funksjoner
# --------------------------------------------------------------------------
def test_url_and_series_key() -> None:
    assert norges_bank.BASE == "https://data.norges-bank.no/api/data"
    assert norges_bank.DATAFLOW == "IR"
    assert norges_bank.SERIES_KEY == "B.KPRA.SD"


def test_fetch_builds_expected_params(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    captured: dict = {}

    def fake_get(url: str, *, params=None, timeout=None, headers=None):  # noqa: ANN001
        captured["url"] = url
        captured["params"] = params

        class _Resp:
            content = b"FREQ;TIME_PERIOD;OBS_VALUE\nB;2020-01-02;1.5\n"
            status_code = 200
            url = "https://data.norges-bank.no/api/data/IR/B.KPRA.SD?format=csv"

        return _Resp()

    monkeypatch.setattr(norges_bank, "get", fake_get)

    version = norges_bank.fetch_key_policy_rate(start="2000-01-01")

    assert captured["url"] == f"{norges_bank.BASE}/{norges_bank.DATAFLOW}/{norges_bank.SERIES_KEY}"
    assert captured["params"]["format"] == "csv"
    assert captured["params"]["locale"] == "en"
    assert captured["params"]["startPeriod"] == "2000-01-01"
    assert "endPeriod" not in captured["params"]

    meta = io.read_meta(version)
    assert meta["dataflow"] == "IR"
    assert meta["series_key"] == "B.KPRA.SD"
    assert meta["http_status"] == 200
    assert meta["suffix"] == "csv"


def test_fetch_includes_end_period_when_given(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    captured: dict = {}

    def fake_get(url: str, *, params=None, timeout=None, headers=None):  # noqa: ANN001
        captured["params"] = params

        class _Resp:
            content = b"FREQ;TIME_PERIOD;OBS_VALUE\nB;2020-01-02;1.5\n"
            status_code = 200
            url = "https://data.norges-bank.no/api/data/IR/B.KPRA.SD?format=csv"

        return _Resp()

    monkeypatch.setattr(norges_bank, "get", fake_get)
    norges_bank.fetch_key_policy_rate(start="2000-01-01", end="2020-12-31")

    assert captured["params"]["endPeriod"] == "2020-12-31"


# --------------------------------------------------------------------------
# Ekte nettverk
# --------------------------------------------------------------------------
@pytest.mark.network
def test_fetch_writes_raw_with_provenance(project: Path) -> None:
    version = norges_bank.fetch_key_policy_rate(start="2024-01-01")

    meta = io.read_meta(version)
    assert meta["http_status"] == 200
    assert meta["bytes"] > 0
    assert "norges-bank.no" in meta["endpoint"]

    text = io.raw_latest("norges_bank", "styringsrente").read_text(encoding="utf-8")
    assert "TIME_PERIOD" in text
    assert "OBS_VALUE" in text
