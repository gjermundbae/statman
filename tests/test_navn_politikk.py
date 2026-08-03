"""Navn mot politikk: clean, mart og korrelasjonshjelperne.

Rådataene er oppdiktet, med tre år valgt for å teste hver sin ting:

    år    hva den tester
    2000  navnetall mangler (undertrykt), valgtall komplette  -> ikke brukbar
    2001  begge tall til stede                                -> brukbar
    2002  navnetall til stede, FrP mangler i valgtallene       -> ikke brukbar
    2003  begge tall til stede                                -> brukbar

To brukbare år (2001, 2003) er minimum for at en korrelasjon i det hele
tatt er definert. 1999 finnes bare i navneserien, som skal dekke år uten
valg også.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from statman import io, registry
from statman.models.mart_navn_politikk import FRP, HOYRE, KRF, VENSTRE

NAVN_AAR = ["1999", "2000", "2001", "2002", "2003"]
# (andel-prosent, antall) per år. None = undertrykt/manglende, som hos SSB.
NAVN_VERDIER: dict[str, tuple[float | None, int | None]] = {
    "1999": (0.05, 10),
    "2000": (None, None),
    "2001": (0.09, 20),
    "2002": (0.02, 5),
    "2003": (0.03, 8),
}

VALG_AAR = ["2000", "2001", "2002", "2003"]
# parti -> verdi per valgår over. FrP mangler i 2002, slik det mangler for
# Fremskrittspartiet i den ekte 1969-raden. To brukbare år (2001, 2003) er
# minimum for at en korrelasjon i det hele tatt er definert.
PARTIER: dict[str, tuple[float | None, float | None, float | None, float | None]] = {
    "01": (40, 35, 45, 30),  # Arbeiderpartiet — skal ikke telle med i borgerlig
    FRP: (10, 15, None, 12),
    HOYRE: (20, 25, 22, 28),
    KRF: (10, 8, 9, 7),
    VENSTRE: (5, 4, 3, 6),
}


def _navn_doc() -> dict[str, Any]:
    prosent = [NAVN_VERDIER[a][0] for a in NAVN_AAR]
    antall = [NAVN_VERDIER[a][1] for a in NAVN_AAR]
    return {
        "class": "dataset",
        "version": "2.0",
        "label": "10467: Fødte, etter jentenavn og guttenavn 1880-2025",
        "source": "Statistisk sentralbyrå",
        "updated": "2026-01-28T07:00:00Z",
        "id": ["Fornavn", "ContentsCode", "Tid"],
        "size": [1, 2, len(NAVN_AAR)],
        "dimension": {
            "Fornavn": {
                "category": {"index": {"2PREBEN": 0}, "label": {"2PREBEN": "Preben"}}
            },
            "ContentsCode": {
                "category": {
                    "index": {"PersonerProsent": 0, "Personer": 1},
                    "label": {"PersonerProsent": "Andel av fødte (prosent)", "Personer": "Fødte"},
                }
            },
            "Tid": {
                "category": {
                    "index": {a: i for i, a in enumerate(NAVN_AAR)},
                    "label": {a: a for a in NAVN_AAR},
                }
            },
        },
        "value": [*prosent, *antall],
    }


def _valg_doc() -> dict[str, Any]:
    koder = list(PARTIER)
    verdier: list[float | None] = []
    for kode in koder:
        verdier += list(PARTIER[kode])
    return {
        "class": "dataset",
        "version": "2.0",
        "label": "09624: Stortingsvalget. Velgere, etter politisk parti og kjønn (prosent)",
        "source": "Statistisk sentralbyrå",
        "updated": "2025-12-15T07:00:00Z",
        "id": ["PolitParti", "Kjonn", "ContentsCode", "Tid"],
        "size": [len(koder), 1, 1, len(VALG_AAR)],
        "dimension": {
            "PolitParti": {
                "category": {
                    "index": {k: i for i, k in enumerate(koder)},
                    "label": {k: k for k in koder},
                }
            },
            "Kjonn": {"category": {"index": {"0": 0}, "label": {"0": "Begge kjønn"}}},
            "ContentsCode": {"category": {"index": {"Velgere": 0}, "label": {"Velgere": "Velgere"}}},
            "Tid": {
                "category": {
                    "index": {a: i for i, a in enumerate(VALG_AAR)},
                    "label": {a: a for a in VALG_AAR},
                }
            },
        },
        "value": verdier,
    }


@pytest.fixture
def built(project: Path) -> dict[str, registry.BuildResult]:
    io.write_raw("ssb", "10467_preben", json.dumps(_navn_doc()).encode("utf-8"), {"license": "test"})
    io.write_raw("ssb", "09624_velgere", json.dumps(_valg_doc()).encode("utf-8"), {"license": "test"})
    return {r.name: r for r in registry.build(["mart.preben_borgerlig"])}


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------
def test_build_covers_the_whole_chain(built: dict[str, registry.BuildResult]) -> None:
    assert set(built) == {
        "clean.navn_preben",
        "clean.velgere_parti",
        "mart.navn_preben_aar",
        "mart.velgere_borgerlig",
        "mart.preben_borgerlig",
    }


def test_clean_navn_keeps_missing_years_as_null(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("clean.navn_preben")

    assert df.height == len(NAVN_AAR) * 2  # to variabler per år
    tomt = df.filter((pl.col("aar") == 2000) & (pl.col("variabel") == "personer"))
    assert tomt["verdi"].to_list() == [None]


def test_clean_velgere_keeps_all_ten_parties_and_missing_frp(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("clean.velgere_parti")

    assert set(df["parti"].unique()) == set(PARTIER)
    manglende = df.filter((pl.col("aar") == 2002) & (pl.col("parti") == FRP))
    assert manglende["andel_velgere_pst"].to_list() == [None]


# --------------------------------------------------------------------------
# mart
# --------------------------------------------------------------------------
def test_navn_pivots_to_one_row_per_year(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.navn_preben_aar").sort("aar")

    assert df.height == len(NAVN_AAR)
    rad_2001 = df.filter(pl.col("aar") == 2001).row(0, named=True)
    assert rad_2001["fodte_gutter"] == 20
    assert rad_2001["andel_fodte_pst"] == pytest.approx(0.09)
    rad_2000 = df.filter(pl.col("aar") == 2000).row(0, named=True)
    assert rad_2000["fodte_gutter"] is None
    assert rad_2000["andel_fodte_pst"] is None


def test_borgerlig_sums_only_the_four_parties(built: dict[str, registry.BuildResult]) -> None:
    """Arbeiderpartiet er med i rådataene, men skal ikke telle med i summen."""
    df = io.load("mart.velgere_borgerlig")
    rad_2001 = df.filter(pl.col("aar") == 2001).row(0, named=True)

    assert rad_2001["borgerlig_andel_pst"] == pytest.approx(25 + 15 + 8 + 4)


def test_borgerlig_is_null_when_one_party_is_missing_not_undercounted(
    built: dict[str, registry.BuildResult],
) -> None:
    """2002 mangler FrP. Summen skal bli null, ikke 22+9+3 = 34."""
    df = io.load("mart.velgere_borgerlig")
    rad_2002 = df.filter(pl.col("aar") == 2002).row(0, named=True)

    assert rad_2002["borgerlig_andel_pst"] is None


def test_koblet_tabell_only_has_election_years(built: dict[str, registry.BuildResult]) -> None:
    """1999 finnes bare i navneserien og skal ikke bli en egen rad."""
    df = io.load("mart.preben_borgerlig")

    assert set(df["aar"].to_list()) == {2000, 2001, 2002, 2003}


def test_brukbar_is_false_for_each_distinct_reason(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.preben_borgerlig")
    brukbar = dict(zip(df["aar"].to_list(), df["brukbar"].to_list()))

    assert brukbar == {2000: False, 2001: True, 2002: False, 2003: True}

    rad_2000 = df.filter(pl.col("aar") == 2000).row(0, named=True)
    assert rad_2000["andel_fodte_preben_pst"] is None  # navnetallet mangler
    assert rad_2000["borgerlig_andel_pst"] is not None  # valgtallet finnes

    rad_2002 = df.filter(pl.col("aar") == 2002).row(0, named=True)
    assert rad_2002["andel_fodte_preben_pst"] is not None  # navnetallet finnes
    assert rad_2002["borgerlig_andel_pst"] is None  # valgtallet mangler (FrP)


# --------------------------------------------------------------------------
# Statistikkhjelperne i eksempelet
# --------------------------------------------------------------------------
def test_pearson_is_plus_one_for_a_perfect_line() -> None:
    from examples.preben_borgerlig import _pearson

    assert _pearson([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_pearson_is_minus_one_for_a_perfect_inverse_line() -> None:
    from examples.preben_borgerlig import _pearson

    assert _pearson([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(1.0 * -1.0)


def test_p_value_is_one_when_there_is_no_correlation_at_all() -> None:
    from examples.preben_borgerlig import t_test_p

    assert t_test_p(0.0, 20) == pytest.approx(1.0, abs=1e-9)


def test_p_value_is_near_zero_for_a_strong_correlation_with_enough_points() -> None:
    from examples.preben_borgerlig import t_test_p

    assert t_test_p(0.9, 30) < 0.001


def test_p_value_matches_a_known_reference_value() -> None:
    """r = 0,5 med n = 20 (df = 18) gir t ≈ 2,472, p (tosidig) ≈ 0,0234."""
    from examples.preben_borgerlig import t_test_p

    assert t_test_p(0.5, 20) == pytest.approx(0.0234, abs=2e-3)


# --------------------------------------------------------------------------
# Sakspakken
# --------------------------------------------------------------------------
def test_sakspakke_is_written(built: dict[str, registry.BuildResult], project: Path) -> None:
    real_catalog = Path(__file__).resolve().parent.parent / "catalog" / "metrics.yml"
    (project / "catalog").mkdir(exist_ok=True)
    (project / "catalog" / "metrics.yml").write_text(
        real_catalog.read_text(encoding="utf-8"), encoding="utf-8"
    )

    from examples import preben_borgerlig

    written = preben_borgerlig.main()
    navn = {p.name for p in written}

    assert navn == {
        "preben_borgerlig.csv",
        "tidsserie.png",
        "scatter.png",
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
    # Bare de brukbare årene (2001, 2003) skal inngå i korrelasjonen.
    assert "n = 2 valgår" in notat
