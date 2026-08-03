"""Meningsmålinger mot navn: clean-parsing, årssnitt og endring år for år.

Fire poll-år er valgt for å teste hver sin ting:

    år    måneder  hva den tester
    2008  12       full baseline, borgerlig = 20+10+5+5 = 40
    2009  12       forrige år finnes -> delta regnes ut
    2010  3        ufullstendig år -> borgerlig_andel_pst blir null
    2012  12       2011 mangler helt -> lag() hopper over seg selv,
                    delta skal IKKE regnes ut mot 2010
    2013  12       forrige år (2012) finnes -> delta regnes ut. Gir det
                    andre brukbare delta-paret, så en korrelasjon i det
                    hele tatt er definert (ett punkt er ikke en korrelasjon).

Navnetall finnes for alle fem år, så enhver ``null`` i endringstabellen
kommer fra meningsmålings-siden, ikke fra Preben-siden — det er poenget
med oppsettet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from statman import io, registry
from statman.models.mart_meningsmaling_politikk import FRP, HOYRE, KRF, VENSTRE

_MAANEDER = [
    "Januar", "Februar", "Mars", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Desember",
]

# år -> (antall måneder, {parti: andel})
POLL_AAR: dict[int, tuple[int, dict[str, float]]] = {
    2008: (12, {"Ap": 40.0, HOYRE: 20.0, FRP: 10.0, KRF: 5.0, VENSTRE: 5.0}),
    2009: (12, {"Ap": 30.0, HOYRE: 25.0, FRP: 15.0, KRF: 4.0, VENSTRE: 4.0}),
    2010: (3, {"Ap": 20.0, HOYRE: 30.0, FRP: 20.0, KRF: 3.0, VENSTRE: 3.0}),
    2012: (12, {"Ap": 35.0, HOYRE: 25.0, FRP: 12.0, KRF: 4.0, VENSTRE: 3.0}),
    2013: (12, {"Ap": 32.0, HOYRE: 26.0, FRP: 13.0, KRF: 5.0, VENSTRE: 4.0}),
}
PARTIER = ["Ap", HOYRE, FRP, KRF, VENSTRE]

NAVN_VERDIER: dict[int, float] = {2008: 0.05, 2009: 0.06, 2010: 0.02, 2012: 0.03, 2013: 0.04}


def _snitt_csv() -> bytes:
    linjer = [";" + ";".join(PARTIER)]
    for aar in sorted(POLL_AAR, reverse=True):
        maaneder, verdier = POLL_AAR[aar]
        for i in range(maaneder):
            navn = _MAANEDER[i]
            celler = [f"{verdier[p]:.1f}".replace(".", ",") + " (0)" for p in PARTIER]
            linjer.append(f"{navn} '{aar % 100:02d};" + ";".join(celler))
    tekst = "\n".join(linjer) + "\n"
    return tekst.encode("latin-1")


def _navn_doc() -> dict[str, Any]:
    aar_liste = [str(a) for a in sorted(NAVN_VERDIER)]
    prosent = [NAVN_VERDIER[int(a)] for a in aar_liste]
    antall = [10 for _ in aar_liste]  # ikke brukt av testene, bare må finnes
    return {
        "class": "dataset",
        "version": "2.0",
        "label": "10467: Fødte, etter jentenavn og guttenavn 1880-2025",
        "source": "Statistisk sentralbyrå",
        "updated": "2026-01-28T07:00:00Z",
        "id": ["Fornavn", "ContentsCode", "Tid"],
        "size": [1, 2, len(aar_liste)],
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
                    "index": {a: i for i, a in enumerate(aar_liste)},
                    "label": {a: a for a in aar_liste},
                }
            },
        },
        "value": [*prosent, *antall],
    }


@pytest.fixture
def built(project: Path) -> dict[str, registry.BuildResult]:
    io.write_raw("pollofpolls", "stortinget_snitt", _snitt_csv(), {"license": "test"}, suffix="csv")
    io.write_raw("ssb", "10467_preben", json.dumps(_navn_doc()).encode("utf-8"), {"license": "test"})
    return {r.name: r for r in registry.build(["mart.preben_trend"])}


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------
def test_build_covers_the_whole_chain(built: dict[str, registry.BuildResult]) -> None:
    assert set(built) == {
        "clean.meningsmaling_parti",
        "clean.navn_preben",
        "mart.meningsmaling_aar",
        "mart.navn_preben_aar",
        "mart.velgere_borgerlig_meningsmaling",
        "mart.preben_trend",
    }


def test_clean_decodes_latin1_party_names_correctly(built: dict[str, registry.BuildResult]) -> None:
    """Høyre skal bli Høyre, ikke H�yre."""
    df = io.load("clean.meningsmaling_parti")

    assert HOYRE in set(df["parti"].unique())
    assert df.height == sum(m for m, _ in POLL_AAR.values()) * len(PARTIER)


def test_clean_splits_the_combined_cell_into_share_and_seats(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("clean.meningsmaling_parti")
    rad = df.filter(
        (pl.col("aar") == 2008) & (pl.col("maaned") == 1) & (pl.col("parti") == HOYRE)
    ).row(0, named=True)

    assert rad["andel_velgere_pst"] == pytest.approx(20.0)
    assert rad["mandater"] == 0


# --------------------------------------------------------------------------
# mart
# --------------------------------------------------------------------------
def test_annual_average_is_the_mean_of_the_months(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.meningsmaling_aar")
    rad = df.filter((pl.col("aar") == 2008) & (pl.col("parti") == HOYRE)).row(0, named=True)

    assert rad["andel_velgere_pst"] == pytest.approx(20.0)
    assert rad["maaneder"] == 12


def test_borgerlig_sums_only_the_four_parties(built: dict[str, registry.BuildResult]) -> None:
    """Ap er med i rådataene, men skal ikke telle med i summen."""
    df = io.load("mart.velgere_borgerlig_meningsmaling")
    rad_2008 = df.filter(pl.col("aar") == 2008).row(0, named=True)

    assert rad_2008["borgerlig_andel_pst"] == pytest.approx(20 + 10 + 5 + 5)


def test_partial_year_gets_a_null_average_not_a_misleading_one(
    built: dict[str, registry.BuildResult],
) -> None:
    """2010 har bare tre måneder. Snittet skal ikke late som det er tolv."""
    df = io.load("mart.velgere_borgerlig_meningsmaling")
    rad_2010 = df.filter(pl.col("aar") == 2010).row(0, named=True)

    assert rad_2010["maaneder"] == 3
    assert rad_2010["borgerlig_andel_pst"] is None


def test_koblet_tabell_only_has_poll_years(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.preben_trend")

    assert set(df["aar"].to_list()) == {2008, 2009, 2010, 2012, 2013}


def test_brukbar_niva_is_false_only_for_the_partial_year(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.preben_trend")
    brukbar = dict(zip(df["aar"].to_list(), df["brukbar_niva"].to_list()))

    assert brukbar == {2008: True, 2009: True, 2010: False, 2012: True, 2013: True}


def test_delta_is_computed_for_a_normal_consecutive_pair(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.preben_trend")
    rad_2009 = df.filter(pl.col("aar") == 2009).row(0, named=True)

    assert rad_2009["delta_borgerlig_pst"] == pytest.approx(48 - 40)
    assert rad_2009["delta_andel_fodte_preben_pst"] == pytest.approx(0.06 - 0.05)
    assert rad_2009["brukbar_delta"] is True


def test_delta_is_null_when_the_prior_year_is_a_partial_year(
    built: dict[str, registry.BuildResult],
) -> None:
    """2010s borgerlig-tall er null (ufullstendig år), så delta må bli null."""
    df = io.load("mart.preben_trend")
    rad_2010 = df.filter(pl.col("aar") == 2010).row(0, named=True)

    assert rad_2010["delta_borgerlig_pst"] is None
    assert rad_2010["brukbar_delta"] is False


def test_delta_skips_a_gap_instead_of_comparing_across_it(
    built: dict[str, registry.BuildResult],
) -> None:
    """2011 finnes ikke i det hele tatt. 2012 skal IKKE få en 'endring' mot
    2010 bare fordi det er forrige rad i tabellen."""
    df = io.load("mart.preben_trend")
    rad_2012 = df.filter(pl.col("aar") == 2012).row(0, named=True)

    assert rad_2012["delta_borgerlig_pst"] is None
    assert rad_2012["delta_andel_fodte_preben_pst"] is None
    assert rad_2012["brukbar_delta"] is False


def test_first_year_has_no_prior_year_to_diff_against(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.preben_trend")
    rad_2008 = df.filter(pl.col("aar") == 2008).row(0, named=True)

    assert rad_2008["delta_borgerlig_pst"] is None
    assert rad_2008["brukbar_delta"] is False


# --------------------------------------------------------------------------
# Sakspakken
# --------------------------------------------------------------------------
def test_sakspakke_is_written(built: dict[str, registry.BuildResult], project: Path) -> None:
    real_catalog = Path(__file__).resolve().parent.parent / "catalog" / "metrics.yml"
    (project / "catalog").mkdir(exist_ok=True)
    (project / "catalog" / "metrics.yml").write_text(
        real_catalog.read_text(encoding="utf-8"), encoding="utf-8"
    )

    from examples import preben_meningsmalinger

    written = preben_meningsmalinger.main()
    navn = {p.name for p in written}

    assert navn == {
        "preben_meningsmalinger.csv",
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
    assert "## Metode" in notat
    assert "## Forbehold" in notat
    # 2009 (mot 2008) og 2013 (mot 2012) er de eneste gyldige, påfølgende
    # parene -- 2012 mot 2010 hopper over hullet i 2011 og teller ikke.
    assert "n = 2 år" in notat
