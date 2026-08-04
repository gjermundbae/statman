"""Rente mot boligpris: clean, mart og hull-håndteringen i endringstallet.

Fem kvartal i rentetallene (kontinuerlig), fire i boligtallene — 2020K3
mangler helt fra boligprisserien, ikke bare den sesongjusterte varianten.
Det tester nøyaktig det ``mart.rente_bolig_kvartal`` er bygget for å
håndtere: at endringen over det hullet ikke blir lest som én kvartals
endring når det egentlig er to.

    kvartal   rente   boligindeks   sesjustert
    2020K1    1,00    100           100
    2020K2    0,50    102           104
    2020K3    0,25    (mangler helt fra boligserien)
    2020K4    0,25    106           108
    2021K1    0,00    108           110
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from statman import io, registry

RENTE_DAGER = [
    ("2020-02-15", 1.0),   # 2020K1
    ("2020-05-15", 0.5),   # 2020K2
    ("2020-08-15", 0.25),  # 2020K3 — finnes bare i rentetallene
    ("2020-11-15", 0.25),  # 2020K4
    ("2021-02-15", 0.0),   # 2021K1
]

BOLIG_KVARTAL = ["2020K1", "2020K2", "2020K4", "2021K1"]  # 2020K3 mangler
BOLIGINDEKS = [100.0, 102.0, 106.0, 108.0]
SESJUSTERT = [100.0, 104.0, 108.0, 110.0]


def _rente_csv() -> bytes:
    lines = ["TIME_PERIOD;OBS_VALUE"]
    lines += [f"{dato};{verdi}" for dato, verdi in RENTE_DAGER]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _bolig_doc() -> dict:
    return {
        "class": "dataset",
        "version": "2.0",
        "label": "07221: Prisindeks for brukte boliger, etter region, boligtype og kvartal",
        "source": "Statistisk sentralbyrå",
        "updated": "2026-07-10T06:00:00Z",
        "id": ["Region", "Boligtype", "ContentsCode", "Tid"],
        "size": [1, 1, 2, len(BOLIG_KVARTAL)],
        "dimension": {
            "Region": {"category": {"index": {"TOTAL": 0}, "label": {"TOTAL": "Hele landet"}}},
            "Boligtype": {"category": {"index": {"00": 0}, "label": {"00": "Alle boligtyper"}}},
            "ContentsCode": {
                "category": {
                    "index": {"Boligindeks": 0, "SesJustBoligindeks": 1},
                    "label": {
                        "Boligindeks": "Prisindeks for brukte boliger",
                        "SesJustBoligindeks": "Prisindeks for brukte boliger, sesongjustert",
                    },
                }
            },
            "Tid": {
                "category": {
                    "index": {t: i for i, t in enumerate(BOLIG_KVARTAL)},
                    "label": {t: t for t in BOLIG_KVARTAL},
                }
            },
        },
        "value": [*BOLIGINDEKS, *SESJUSTERT],
    }


@pytest.fixture
def built(project: Path) -> dict[str, registry.BuildResult]:
    io.write_raw("norges_bank", "styringsrente", _rente_csv(), {"license": "test"}, suffix="csv")
    io.write_raw("ssb", "07221_bolig", json.dumps(_bolig_doc()).encode("utf-8"), {"license": "test"})
    return {r.name: r for r in registry.build(["mart.rente_bolig_kvartal"])}


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------
def test_build_covers_the_whole_chain(built: dict[str, registry.BuildResult]) -> None:
    assert set(built) == {
        "clean.styringsrente",
        "clean.boligprisindeks",
        "mart.rente_kvartal",
        "mart.boligpris_kvartal",
        "mart.rente_bolig_kvartal",
    }


def test_clean_styringsrente_has_one_row_per_day(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("clean.styringsrente")
    assert df.height == len(RENTE_DAGER)
    assert df.schema["rente_pst"] == pl.Float64


def test_clean_boligprisindeks_is_long_form(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("clean.boligprisindeks")
    assert df.height == len(BOLIG_KVARTAL) * 2  # to variabler per kvartal
    rad = df.filter((pl.col("kvartal_kode") == "2020K2") & (pl.col("variabel") == "sesjustboligindeks"))
    assert rad["verdi"].to_list() == [104.0]
    assert rad["aar"].to_list() == [2020]
    assert rad["kvartal"].to_list() == [2]


# --------------------------------------------------------------------------
# mart
# --------------------------------------------------------------------------
def test_rente_kvartal_maps_every_calendar_month_to_exactly_one_of_four_quarters(
    project: Path,
) -> None:
    """Regresjonstest: DuckDBs ``/`` er flyttallsdivisjon, og cast til integer
    runder til nærmeste — ikke trunkerer. Med `(month - 1) / 3 + 1` uten
    heltallsdivisjon havner mars/juni/september i kvartalet etter sitt eget,
    og desember runder helt ut til et ikke-eksisterende "kvartal 5". Denne
    testen bruker én dag i hver av årets tolv måneder, nettopp for å fange
    opp brytningspunktene månedene 3, 6, 9 og 12 er, i motsetning til
    ``built``-fixturen over som bare bruker dag 15 midt i kvartalet.
    """
    lines = ["TIME_PERIOD;OBS_VALUE"]
    for maaned in range(1, 13):
        lines.append(f"2022-{maaned:02d}-10;1.0")
    io.write_raw("norges_bank", "styringsrente", ("\n".join(lines) + "\n").encode("utf-8"), {"license": "test"}, suffix="csv")

    registry.build(["mart.rente_kvartal"])
    df = io.load("mart.rente_kvartal").sort("kvartal_indeks")

    assert df["kvartal_kode"].to_list() == ["2022K1", "2022K2", "2022K3", "2022K4"]
    assert df["dager"].to_list() == [3, 3, 3, 3]


def test_rente_kvartal_covers_all_five_quarters_including_the_one_without_housing_data(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.rente_kvartal").sort("kvartal_indeks")
    assert df["kvartal_kode"].to_list() == ["2020K1", "2020K2", "2020K3", "2020K4", "2021K1"]
    assert df["dager"].to_list() == [1, 1, 1, 1, 1]
    rad = df.filter(pl.col("kvartal_kode") == "2020K3").row(0, named=True)
    assert rad["rente_snitt_pst"] == pytest.approx(0.25)


def test_boligpris_kvartal_pivots_to_one_row_per_quarter(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.boligpris_kvartal").sort("kvartal_indeks")
    assert df.height == 4
    rad = df.filter(pl.col("kvartal_kode") == "2020K4").row(0, named=True)
    assert rad["boligindeks"] == pytest.approx(106.0)
    assert rad["boligindeks_sesjustert"] == pytest.approx(108.0)


def test_koblet_tabell_is_driven_by_housing_data_so_2020k3_is_absent(
    built: dict[str, registry.BuildResult],
) -> None:
    """2020K3 finnes bare i rentetallene og skal ikke bli en egen rad."""
    df = io.load("mart.rente_bolig_kvartal")
    assert set(df["kvartal_kode"].to_list()) == {"2020K1", "2020K2", "2020K4", "2021K1"}


def test_delta_is_null_across_the_missing_quarter_not_a_two_quarter_jump(
    built: dict[str, registry.BuildResult],
) -> None:
    """2020K4 følger 2020K3 (som mangler) i kalenderen, ikke 2020K2 (forrige rad i tabellen)."""
    df = io.load("mart.rente_bolig_kvartal")
    rad = df.filter(pl.col("kvartal_kode") == "2020K4").row(0, named=True)

    assert rad["delta_rente_pp"] is None
    assert rad["endring_bolig_kvartal_pst"] is None


def test_delta_is_computed_for_genuinely_consecutive_quarters(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.rente_bolig_kvartal")

    q2 = df.filter(pl.col("kvartal_kode") == "2020K2").row(0, named=True)
    assert q2["delta_rente_pp"] == pytest.approx(0.5 - 1.0)
    assert q2["endring_bolig_kvartal_pst"] == pytest.approx(104.0 / 100.0 - 1.0)

    q1_2021 = df.filter(pl.col("kvartal_kode") == "2021K1").row(0, named=True)
    assert q1_2021["delta_rente_pp"] == pytest.approx(0.0 - 0.25)
    assert q1_2021["endring_bolig_kvartal_pst"] == pytest.approx(110.0 / 108.0 - 1.0)


def test_first_quarter_has_no_previous_quarter_to_compare_against(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.rente_bolig_kvartal")
    q1 = df.filter(pl.col("kvartal_kode") == "2020K1").row(0, named=True)
    assert q1["delta_rente_pp"] is None
    assert q1["brukbar_niva"] is True


# --------------------------------------------------------------------------
# Lag-hjelperne i eksempelet
# --------------------------------------------------------------------------
def test_lag_table_finds_only_the_one_genuinely_consecutive_pair_at_lag_zero(
    built: dict[str, registry.BuildResult],
) -> None:
    """Med bare to par som er faktisk sammenhengende (K1->K2 og K4->K1'21), skal svaret her være lite.

    Sjekker bare at funksjonen ikke krasjer og at n telles riktig — med så
    lite data er ikke r selv meningsfullt (under 3 par gir ``None``).
    """
    from examples.rente_bolig import _lag_table

    df = io.load("mart.rente_bolig_kvartal")
    rader = _lag_table(df)
    by_lag = {lag: (n, r) for lag, n, r, _p in rader}

    # Ved lag 0 er begge par brukbare (delta og endring finnes for K2 og K1'21).
    n0, _ = by_lag[0]
    assert n0 == 2


# --------------------------------------------------------------------------
# Sakspakken — trenger nok sammenhengende kvartal til at hovedforskyvningen
# (1 kvartal, se examples/rente_bolig.py) har minst tre par å regne r av.
# Ti kvartal på rad, ingen hull, er nok til det.
# --------------------------------------------------------------------------
_LANGE_KVARTAL = [f"{aar}K{k}" for aar in (2018, 2019) for k in (1, 2, 3, 4)] + ["2020K1", "2020K2"]


def _lang_rente_csv() -> bytes:
    lines = ["TIME_PERIOD;OBS_VALUE"]
    maaned = {1: "02", 2: "05", 3: "08", 4: "11"}
    for i, kode in enumerate(_LANGE_KVARTAL):
        aar, kvartal = int(kode[:4]), int(kode[5])
        lines.append(f"{aar}-{maaned[kvartal]}-15;{1.0 + 0.1 * i}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _lang_bolig_doc() -> dict:
    n = len(_LANGE_KVARTAL)
    boligindeks = [100.0 + 2 * i for i in range(n)]
    sesjustert = [99.0 + 1.7 * i for i in range(n)]
    return {
        "class": "dataset",
        "version": "2.0",
        "label": "07221: Prisindeks for brukte boliger, etter region, boligtype og kvartal",
        "source": "Statistisk sentralbyrå",
        "updated": "2026-07-10T06:00:00Z",
        "id": ["Region", "Boligtype", "ContentsCode", "Tid"],
        "size": [1, 1, 2, n],
        "dimension": {
            "Region": {"category": {"index": {"TOTAL": 0}, "label": {"TOTAL": "Hele landet"}}},
            "Boligtype": {"category": {"index": {"00": 0}, "label": {"00": "Alle boligtyper"}}},
            "ContentsCode": {
                "category": {
                    "index": {"Boligindeks": 0, "SesJustBoligindeks": 1},
                    "label": {
                        "Boligindeks": "Prisindeks for brukte boliger",
                        "SesJustBoligindeks": "Prisindeks for brukte boliger, sesongjustert",
                    },
                }
            },
            "Tid": {
                "category": {
                    "index": {t: i for i, t in enumerate(_LANGE_KVARTAL)},
                    "label": {t: t for t in _LANGE_KVARTAL},
                }
            },
        },
        "value": [*boligindeks, *sesjustert],
    }


@pytest.fixture
def built_sakspakke(project: Path) -> dict[str, registry.BuildResult]:
    io.write_raw("norges_bank", "styringsrente", _lang_rente_csv(), {"license": "test"}, suffix="csv")
    io.write_raw("ssb", "07221_bolig", json.dumps(_lang_bolig_doc()).encode("utf-8"), {"license": "test"})
    return {r.name: r for r in registry.build(["mart.rente_bolig_kvartal"])}


def test_sakspakke_is_written(built_sakspakke: dict[str, registry.BuildResult], project: Path) -> None:
    real_catalog = Path(__file__).resolve().parent.parent / "catalog" / "metrics.yml"
    (project / "catalog").mkdir(exist_ok=True)
    (project / "catalog" / "metrics.yml").write_text(
        real_catalog.read_text(encoding="utf-8"), encoding="utf-8"
    )

    from examples import rente_bolig

    written = rente_bolig.main()
    navn = {p.name for p in written}

    assert navn == {
        "rente_bolig.csv",
        "tidsserie.png",
        "niva_vs_endring.png",
        "notat.md",
        "artikkel.json",
    }
    assert all(p.exists() and p.stat().st_size > 0 for p in written)
    for png in (p for p in written if p.suffix == ".png"):
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    notat = next(p for p in written if p.suffix == ".md").read_text(encoding="utf-8")
    assert "## Funn" in notat
    assert "## Følsomhet" in notat
    assert "## Metode" in notat
    assert "## Forbehold" in notat
