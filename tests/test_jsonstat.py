"""Tester for json-stat2-dekoderen. Ingen nettverk.

Det som kan gå galt her er rekkefølgen: json-stat2 er en flat liste, og
brettes den ut feil vei havner alle tallene på feil kommune uten at noe
krasjer. Derfor sjekker testene celle for celle mot en tabell som er
regnet ut for hånd.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from statman import jsonstat


def _doc(**overstyr: Any) -> dict[str, Any]:
    """Et lite json-stat2-dokument: 2 regioner × 3 år."""
    doc: dict[str, Any] = {
        "class": "dataset",
        "version": "2.0",
        "label": "Testtabell",
        "source": "Ingen",
        "updated": "2026-04-15T06:00:00Z",
        "id": ["Region", "Tid"],
        "size": [2, 3],
        "dimension": {
            "Region": {
                "label": "region",
                "category": {
                    "index": {"0301": 0, "1103": 1},
                    "label": {"0301": "Oslo", "1103": "Stavanger"},
                },
            },
            "Tid": {
                "label": "år",
                "category": {
                    "index": {"2024": 0, "2025": 1, "2026": 2},
                    "label": {"2024": "2024", "2025": "2025", "2026": "2026"},
                },
            },
        },
        # Radrekkefølge: Oslo 2024, 2025, 2026, så Stavanger 2024, 2025, 2026.
        "value": [11, 12, 13, 21, 22, 23],
    }
    doc.update(overstyr)
    return doc


def test_to_frame_shape_and_columns() -> None:
    df = jsonstat.to_frame(_doc())

    assert df.height == 6
    assert df.columns == ["region", "region_label", "tid", "tid_label", "value", "status"]
    assert df.schema["value"] == pl.Float64
    assert df.schema["region"] == pl.Utf8


def test_to_frame_unfolds_in_row_major_order() -> None:
    """Siste dimensjon varierer raskest. Bytter man om, blir tallene feil."""
    df = jsonstat.to_frame(_doc())

    assert df["region"].to_list() == ["0301"] * 3 + ["1103"] * 3
    assert df["tid"].to_list() == ["2024", "2025", "2026"] * 2
    assert df["value"].to_list() == [11, 12, 13, 21, 22, 23]


def test_each_cell_lands_on_its_own_code() -> None:
    df = jsonstat.to_frame(_doc())
    oppslag = {(r["region"], r["tid"]): r["value"] for r in df.iter_rows(named=True)}

    assert oppslag[("0301", "2024")] == 11
    assert oppslag[("1103", "2026")] == 23
    assert oppslag[("1103", "2024")] == 21


def test_labels_follow_the_codes() -> None:
    df = jsonstat.to_frame(_doc())
    navn = dict(zip(df["region"].to_list(), df["region_label"].to_list()))

    assert navn == {"0301": "Oslo", "1103": "Stavanger"}


def test_index_may_be_a_list() -> None:
    """Noen produsenter oppgir index som liste i stedet for kart."""
    doc = _doc()
    doc["dimension"]["Region"]["category"]["index"] = ["0301", "1103"]

    assert jsonstat.to_frame(doc)["region"].to_list() == ["0301"] * 3 + ["1103"] * 3


def test_index_may_be_unsorted() -> None:
    """Posisjonen står i verdien, ikke i rekkefølgen nøklene er skrevet."""
    doc = _doc()
    doc["dimension"]["Region"]["category"]["index"] = {"1103": 1, "0301": 0}

    assert jsonstat.to_frame(doc)["region"].to_list() == ["0301"] * 3 + ["1103"] * 3


def test_null_values_survive() -> None:
    """SSB lar ferske perioder stå tomme. De skal bli null, ikke 0."""
    doc = _doc(value=[11, 12, None, 21, 22, None])
    df = jsonstat.to_frame(doc)

    assert df["value"].null_count() == 2
    assert df.filter(pl.col("tid") == "2026")["value"].to_list() == [None, None]


def test_sparse_value_map() -> None:
    """``value`` kan være et kart fra celleindeks i stedet for en liste."""
    doc = _doc(value={"0": 11, "5": 23})
    df = jsonstat.to_frame(doc)

    assert df["value"].to_list() == [11, None, None, None, None, 23]


def test_status_is_read_per_cell() -> None:
    doc = _doc(value=[11, 12, None, 21, 22, None], status={"2": "..", "5": ".."})
    df = jsonstat.to_frame(doc)

    assert df["status"].to_list() == [None, None, "..", None, None, ".."]


def test_status_missing_gives_all_null() -> None:
    assert jsonstat.to_frame(_doc())["status"].null_count() == 6


def test_header_picks_up_provenance() -> None:
    assert jsonstat.header(_doc()) == {
        "label": "Testtabell",
        "source": "Ingen",
        "updated": "2026-04-15T06:00:00Z",
    }


def test_reads_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text(json.dumps(_doc()), encoding="utf-8")

    assert jsonstat.to_frame(path).height == 6
    assert jsonstat.header(path)["label"] == "Testtabell"


def test_value_count_must_match_dimensions() -> None:
    with pytest.raises(ValueError, match="verdier"):
        jsonstat.to_frame(_doc(value=[1, 2, 3]))


def test_category_count_must_match_size() -> None:
    doc = _doc()
    doc["size"] = [3, 3]
    with pytest.raises(ValueError, match="koder"):
        jsonstat.to_frame(doc)


def test_column_name_lowercases() -> None:
    assert jsonstat.column_name("ContentsCode") == "contentscode"
    assert jsonstat.column_name("Tid") == "tid"
