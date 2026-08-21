"""Tester for EUROCONTROL/PRB-konnektoren og trafikk-/kapasitetsmodellene.

Rapportene er PDF med løpende tekst, ikke en datatabell — se
``statman/models/clean_eurocontrol_norge.py``. De rene testene kjører derfor
``parse_report`` direkte på tekst i samme form som rapportene faktisk bruker
(kontrollert manuelt mot alle fem virkelige PDF-ene under research), uten å
dra inn en PDF-genererende avhengighet bare for testenes skyld. Modell- og
mart-testene monkeypatcher ``_report_text`` til å returnere kortere,
syntetiske utdrag av samme mønster. Nettverkstesten kjører hele kjeden mot
de ekte rapportene og sjekker de samme tallene som ble verifisert manuelt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from statman import io, registry
from statman.models import clean_eurocontrol_norge as m
from statman.sources import eurocontrol


# --------------------------------------------------------------------------
# parse_report — rene tester
# --------------------------------------------------------------------------
def test_parse_report_trafikk() -> None:
    text = (
        "Norway recorded 549K actual IFR movements in 2024, +0.4% compared "
        "to 2023 (547K). Actual 2024 IFR movements represent 93% of the "
        "actual 2019 level (591K)."
    )
    parsed = m.parse_report(text, 2024)
    assert parsed["ifr_bevegelser_1000"] == 549.0
    assert m._trafikk_2019(text) == 591.0


def test_parse_report_produktivitet_og_sektortimer() -> None:
    text = (
        "Bodo ACC registered 7.62 IFR movements per one sector opening hour "
        "in 2024, being 26.9% above 2019. The yearly total of sector "
        "opening hours in Bodo ACC was 24,161, showing a 2.1% decrease "
        "compared to 2023."
    )
    parsed = m.parse_report(text, 2024)
    assert parsed["produktivitet"] == {"Bodo": 7.62}
    assert parsed["sektortimer"] == {"Bodo": 24_161}


def test_parse_report_atco_bemanning() -> None:
    text = "The number of ATCOs in OPS is 40, being below the 2024 plan in Bodo by 2 FTEs."
    parsed = m.parse_report(text, 2024)
    assert parsed["atco"] == {"Bodo": {"ops": 40, "plan": 42}}


def test_parse_report_mangler_forblir_tomt() -> None:
    """Et forhold som ikke nevnes gir et tomt oppslag, ikke en gjettet verdi."""
    parsed = m.parse_report("Ingenting relevant nevnt her i det hele tatt.", 2022)
    assert parsed["ifr_bevegelser_1000"] is None
    assert parsed["produktivitet"] == {}
    assert parsed["sektortimer"] == {}
    assert parsed["atco"] == {}


def test_thousands_separator_number_not_truncated_before_a_non_comma() -> None:
    """Regressjonstest: tallet står ikke alltid rett før et komma.

    De fleste årene skriver rapporten «... was 24,161, showing ...», men
    2022-rapporten skriver «... was 15,689 in 2022, showing ...» — komma
    kommer først etter årstallet, ikke rett etter tallet. En tidligere
    versjon av regexen krevde komma rett etter og kappet det til «15».
    """
    text = "sector opening hours in Oslo ACC was 15,689 in 2022, showing a 9.3% increase."
    parsed = m.parse_report(text, 2022)
    assert parsed["sektortimer"] == {"Oslo": 15_689}


# --------------------------------------------------------------------------
# Kildehenting — offline
# --------------------------------------------------------------------------
def test_fetch_builds_expected_url(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    captured: dict = {}

    def fake_get(url: str, *, timeout=None):  # noqa: ANN001
        captured["url"] = url

        class _Resp:
            content = b"%PDF-1.4 test"
            status_code = 200
            url = "https://www.sesperformance.eu/download/2024/PRB-Annual-Monitoring-Report_Norway_2024.pdf"

        return _Resp()

    monkeypatch.setattr(eurocontrol, "get", fake_get)
    version = eurocontrol.fetch_prb_norway(2024)

    assert captured["url"] == (
        "https://www.sesperformance.eu/download/2024/"
        "PRB-Annual-Monitoring-Report_Norway_2024.pdf"
    )
    meta = io.read_meta(version)
    assert meta["year"] == 2024
    assert meta["suffix"] == "pdf"


# --------------------------------------------------------------------------
# Modell + mart — syntetiske rapporttekster, ekte byggegraf
# --------------------------------------------------------------------------
_TEKST: dict[int, str] = {
    2020: (
        "Norway recorded 344K actual IFR movements in 2020. "
        "Actual 2020 IFR movements represent 58% of the actual 2019 level (591K). "
        "Bodo ACC registered 5.47 IFR movements per one sector opening hour in 2020. "
        "The yearly total of sector opening hours in Bodo ACC was 26,445."
    ),
    2021: (
        "Norway recorded 374K actual IFR movements in 2021. "
        "Bodo ACC registered 7.19 IFR movements per one sector opening hour in 2021. "
        "The yearly total of sector opening hours in Bodo ACC was 22,463."
    ),
    2022: (
        "Norway recorded 525K actual IFR movements in 2022. "
        "Oslo ACC registered 13.36 IFR movements per one sector opening hour in 2022. "
        "The yearly total of sector opening hours in Oslo ACC was 15,689 in 2022, showing an increase."
    ),
    2023: (
        "Norway recorded 547K actual IFR movements in 2023. "
        "Bodo ACC registered 7.33 IFR movements per one sector opening hour in 2023. "
        "The yearly total of sector opening hours in Bodo ACC was 24,686."
    ),
    2024: (
        "Norway recorded 549K actual IFR movements in 2024. "
        "Bodo ACC registered 7.62 IFR movements per one sector opening hour in 2024. "
        "The yearly total of sector opening hours in Bodo ACC was 24,161. "
        "The number of ATCOs in OPS is 40, being below the 2024 plan in Bodo by 2 FTEs. "
        "The number of ATCOs in OPS is 90, being below the 2024 plan in Oslo by 14 FTEs. "
        "The number of ATCOs in OPS is 29, being below the 2024 plan in Stavanger by 2 FTEs."
    ),
}


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch, project: Path) -> dict[str, registry.BuildResult]:
    for year in m.YEARS:
        io.write_raw(
            "eurocontrol", f"prb_norway_{year}", b"dummy", {"license": "test"}, suffix="pdf"
        )

    def fake_report_text(path: Path) -> str:
        # path er .../raw/eurocontrol/prb_norway_<year>/<stamp>/data.pdf
        year = int(path.parent.parent.name.rsplit("_", 1)[-1])
        return _TEKST[year]

    monkeypatch.setattr(m, "_report_text", fake_report_text)

    return {
        r.name: r
        for r in registry.build(
            [
                "mart.eurocontrol_bodo_arbeidsbelastning",
                "mart.eurocontrol_bemanning_2024",
            ]
        )
    }


def test_trafikk_series_covers_2019_through_2024(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("clean.eurocontrol_trafikk_norge").sort("aar")
    assert df["aar"].to_list() == [2019, 2020, 2021, 2022, 2023, 2024]
    assert df.filter(df["aar"] == 2019)["ifr_bevegelser_1000"].item() == 591.0
    assert df.filter(df["aar"] == 2024)["ifr_bevegelser_1000"].item() == 549.0


def test_kapasitet_only_has_rows_where_something_is_actually_reported(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("clean.eurocontrol_kapasitet")
    # Oslo og Stavanger har ikke et Bodø-rad hvert år; 2022 for Bodø mangler helt.
    assert df.filter((df["acc"] == "Bodo") & (df["aar"] == 2022)).height == 0
    oslo_2022 = df.filter((df["acc"] == "Oslo") & (df["aar"] == 2022)).row(0, named=True)
    assert oslo_2022["sektortimer"] == 15_689


def test_bodo_mart_has_a_gap_at_2022_not_a_guess(built: dict[str, registry.BuildResult]) -> None:
    import polars as pl

    df = io.load("mart.eurocontrol_bodo_arbeidsbelastning")
    rad_2022 = df.filter(pl.col("aar") == 2022).row(0, named=True)
    assert rad_2022["bodo_sektortimer"] is None
    assert rad_2022["bodo_ifr_per_sektortime"] is None
    assert rad_2022["ifr_bevegelser_norge_1000"] == 525.0

    rad_2024 = df.filter(pl.col("aar") == 2024).row(0, named=True)
    assert rad_2024["bodo_ifr_per_sektortime"] == 7.62


def test_bemanning_2024_all_three_acc_under_plan(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.eurocontrol_bemanning_2024").sort("acc")
    assert df["acc"].to_list() == ["Bodo", "Oslo", "Stavanger"]
    assert df["atco_under_plan"].to_list() == [2, 14, 2]
    assert (df["atco_plan"] >= df["atco_ops"]).all()


# --------------------------------------------------------------------------
# Ekte nettverk
# --------------------------------------------------------------------------
@pytest.mark.network
def test_fetch_writes_raw_pdf(project: Path) -> None:
    version = eurocontrol.fetch_prb_norway(2024)
    meta = io.read_meta(version)
    assert meta["http_status"] == 200
    assert meta["bytes"] > 100_000
    assert meta["suffix"] == "pdf"


@pytest.mark.network
def test_real_reports_match_manually_verified_figures(project: Path) -> None:
    for year in m.YEARS:
        eurocontrol.fetch_prb_norway(year)

    results = {
        r.name: r
        for r in registry.build(
            ["mart.eurocontrol_bodo_arbeidsbelastning", "mart.eurocontrol_bemanning_2024"]
        )
    }
    assert results

    trafikk = io.load("clean.eurocontrol_trafikk_norge")
    assert trafikk.filter(trafikk["aar"] == 2019)["ifr_bevegelser_1000"].item() == 591.0
    assert trafikk.filter(trafikk["aar"] == 2024)["ifr_bevegelser_1000"].item() == 549.0

    bemanning = io.load("mart.eurocontrol_bemanning_2024").sort("acc")
    assert bemanning["atco_ops"].to_list() == [40, 90, 29]
    assert bemanning["atco_under_plan"].to_list() == [2, 14, 2]
