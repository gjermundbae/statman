"""Ende-til-ende: syntetisk kilde -> clean -> mart -> sakspakke i output/."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from statman import io, registry
from statman.sources import synthetic

EXPECTED_MONTHS = (synthetic.END_YEAR - synthetic.START_YEAR + 1) * 12
EXPECTED_ROWS = EXPECTED_MONTHS * len(synthetic.AREAS)


TARGET = "mart.kraftpris_maaned"


@pytest.fixture
def built(project: Path) -> list[registry.BuildResult]:
    # Bare kraftpriskjeden. `registry.build()` uten mål ville tatt med
    # SSB-modellene, som trenger rådata denne testen ikke har.
    synthetic.ingest(seed=1)
    return registry.build([TARGET])


def test_generators_are_deterministic() -> None:
    assert synthetic.generate_kraftpris(7) == synthetic.generate_kraftpris(7)
    assert synthetic.generate_kraftpris(7) != synthetic.generate_kraftpris(8)


def test_ingest_writes_both_datasets_with_provenance(project: Path) -> None:
    written = synthetic.ingest()

    assert set(written) == {"kraftpris", "kpi"}
    meta = io.read_meta(written["kraftpris"])
    assert meta["rows"] == EXPECTED_ROWS
    assert "syntetiske" in meta["license"]
    assert meta["sha256"]


def test_build_produces_all_models(built: list[registry.BuildResult]) -> None:
    names = {r.name for r in built}
    assert {"clean.kraftpris", "clean.kpi", "mart.kraftpris_maaned"} <= names
    assert all(r.path.exists() for r in built)

    by_name = {r.name: r for r in built}
    assert by_name["clean.kpi"].rows == EXPECTED_MONTHS
    assert by_name["clean.kraftpris"].rows == EXPECTED_ROWS
    assert by_name["mart.kraftpris_maaned"].rows == EXPECTED_ROWS


def test_clean_layer_types_and_parsing(built: list[registry.BuildResult]) -> None:
    df = io.load("clean.kraftpris")

    assert df.schema["month"] == pl.Date
    assert df.schema["ore_per_kwh"] == pl.Float64
    assert df["month"].min().year == synthetic.START_YEAR
    assert df["month"].max().year == synthetic.END_YEAR
    assert df["month"].max().month == 12
    assert set(df["prisomrade"].unique().to_list()) == set(synthetic.AREAS)


def test_deflation_is_arithmetically_right(built: list[registry.BuildResult]) -> None:
    mart = io.load("mart.kraftpris_maaned")
    kpi = io.load("clean.kpi")
    kpi_ref = kpi.sort("month")["indeks_2015"][-1]

    row = mart.sort("month").row(0, named=True)
    expected = row["ore_nominell"] * kpi_ref / row["kpi"]
    assert row["ore_faste_kroner"] == pytest.approx(expected, rel=1e-3)


def test_last_month_real_equals_nominal(built: list[registry.BuildResult]) -> None:
    """Referansemåneden er siste måned, så der skal de to seriene møtes."""
    mart = io.load("mart.kraftpris_maaned")
    last = mart.filter(pl.col("month") == mart["month"].max())

    for row in last.iter_rows(named=True):
        assert row["ore_faste_kroner"] == pytest.approx(row["ore_nominell"], rel=1e-3)


def test_deflation_lifts_early_years(built: list[registry.BuildResult]) -> None:
    """Gamle nominelle kroner skal bli større når de regnes om til dagens kroner."""
    mart = io.load("mart.kraftpris_maaned")
    first = mart.sort("month").head(len(synthetic.AREAS))

    assert (first["ore_faste_kroner"] > first["ore_nominell"]).all()


def test_yoy_is_null_for_first_year_then_populated(built: list[registry.BuildResult]) -> None:
    mart = io.load("mart.kraftpris_maaned").sort(["prisomrade", "month"])
    no1 = mart.filter(pl.col("prisomrade") == "NO1")

    assert no1["endring_12m_realt"].head(12).null_count() == 12
    assert no1["endring_12m_realt"].tail(12).null_count() == 0


def test_southern_areas_hit_harder_by_shock(built: list[registry.BuildResult]) -> None:
    """Sanity-sjekk på at generatoren lager det mønsteret modellene skal vise."""
    mart = io.load("mart.kraftpris_maaned").filter(
        (pl.col("month") >= pl.date(2022, 1, 1)) & (pl.col("month") <= pl.date(2022, 12, 31))
    )
    peak = mart.group_by("prisomrade").agg(pl.col("ore_faste_kroner").mean()).to_dicts()
    means = {row["prisomrade"]: row["ore_faste_kroner"] for row in peak}

    assert means["NO2"] > means["NO4"] * 2


def test_rebuild_is_idempotent(built: list[registry.BuildResult]) -> None:
    before = io.load("mart.kraftpris_maaned")
    registry.build([TARGET])
    assert io.load("mart.kraftpris_maaned").equals(before)


def test_partial_build_only_touches_target(project: Path) -> None:
    synthetic.ingest()
    results = registry.build(["clean.kpi"])

    assert [r.name for r in results] == ["clean.kpi"]
    assert not io.model_path("mart.kraftpris_maaned").exists()


def test_month_label_is_norwegian() -> None:
    import datetime as dt

    from examples.kraftpris_chart import month_label

    assert month_label(dt.date(2025, 12, 1)) == "desember 2025"
    assert month_label(dt.date(2026, 3, 15)) == "mars 2026"
    assert month_label(dt.date(2015, 1, 1)) == "januar 2015"


def test_chart_writes_full_sakspakke(built: list[registry.BuildResult], project: Path) -> None:
    # `examples` finnes på sys.path via pythonpath = ["."] i pyproject.
    # Katalogen må derimot kopieres, siden io.project_root() nå peker på tmp_path.
    real_catalog = Path(__file__).resolve().parent.parent / "catalog" / "metrics.yml"
    (project / "catalog").mkdir(exist_ok=True)
    (project / "catalog" / "metrics.yml").write_text(
        real_catalog.read_text(encoding="utf-8"), encoding="utf-8"
    )

    from examples import kraftpris_chart

    written = kraftpris_chart.main()
    names = {p.name for p in written}

    assert names == {"kraftpris.csv", "kraftpris.png", "notat.md", "artikkel.json"}
    assert all(p.exists() and p.stat().st_size > 0 for p in written)

    png = next(p for p in written if p.suffix == ".png")
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert png.stat().st_size > 10_000

    notat = (next(p for p in written if p.suffix == ".md")).read_text(encoding="utf-8")
    assert "## Funn" in notat
    assert "## Forbehold" in notat
    assert "Nominelle kroner" in notat  # forbehold hentet fra katalogen
    assert "syntetiske" in notat.lower()
    # Månedsnavn skal være norske uansett systemlokale.
    assert f"desember {synthetic.END_YEAR}" in notat
    assert not any(m in notat for m in ("January", "December", "March"))

    csv = pl.read_csv(next(p for p in written if p.suffix == ".csv"))
    assert csv.height == EXPECTED_ROWS
