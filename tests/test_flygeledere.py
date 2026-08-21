"""mart.flygeledere_lonn — to kilder i lang form, med et ekte hull mellom dem.

Fixturen har tre år i den årlige tabellen (2015-2017) og tre kvartaler i
kvartalstabellen (2016K1, 2016K2, 2017K1), og lar kilden selv undertrykke
ett punkt i hver — 2016 i den årlige, 2016K1 i den kvartalsvise — nøyaktig
slik SSB gjør det for flygeledere i virkeligheten: verdien er ``None`` i
json-stat2-svaret, ikke fraværende fra tidsdimensjonen. Det er den samme
mekanismen som skal fange 2021-2024-hullet i de ekte tallene.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from statman import io, registry

YRKE = "3154"
DEKOY = "1111"

# Novemberindeksen for de tre årlige punktene, snittet for de tre
# kvartalene, og til slutt referansen alt deflateres til (2025M11 i den
# ekte modellen — se KPI_REFERANSE_MAANED i statman/models/mart_flygeledere.py).
KPI: dict[str, float] = {
    "2015M11": 90.0,
    "2016M01": 91.0, "2016M02": 91.5, "2016M03": 92.0,  # 2016K1, snitt 91.5
    "2016M04": 92.5, "2016M05": 93.0, "2016M06": 93.5,  # 2016K2, snitt 93.0
    "2016M11": 94.0,
    "2017M01": 95.0, "2017M02": 95.5, "2017M03": 96.0,  # 2017K1, snitt 95.5
    "2017M11": 97.0,
    "2025M11": 120.0,  # referansen
}

# Årlig (11418). 2016 er kildens undertrykte punkt — samme mekanisme som
# flygeledernes ekte 2021-2024-hull.
LONN_AAR: dict[str, dict[str, float | None]] = {
    YRKE: {"2015": 80_000.0, "2016": None, "2017": 88_000.0},
    DEKOY: {"2015": 50_000.0, "2016": 52_000.0, "2017": 54_000.0},
}

# Kvartalsvis (11658). 2016K1 er kildens undertrykte punkt — samme mekanisme
# som flygeledernes ekte "ingen medianlønn før 2025K4".
LONN_KVARTAL: dict[str, dict[str, float | None]] = {
    YRKE: {"2016K1": None, "2016K2": 90_200.0, "2017K1": 91_000.0},
    DEKOY: {"2016K1": 60_000.0, "2016K2": 61_000.0, "2017K1": 62_000.0},
}

# Bestand (11658, Lønnstakere). 2017K1 mangler helt for YRKE — samme
# mekanisme som de ekte 2025K2/K3-hullene i bestanden for flygeledere.
BESTAND: dict[str, dict[str, int | None]] = {
    YRKE: {"2016K1": 520, "2016K2": 515, "2017K1": None},
    DEKOY: {"2016K1": 1_000, "2016K2": 1_010, "2017K1": 1_020},
}

KLASS_KODER: list[dict[str, Any]] = [
    {"code": "3", "parentCode": None, "level": "1", "name": "Høyskoleyrker"},
    {"code": "31", "parentCode": "3", "level": "2", "name": "Skips- og luftfartsyrker"},
    {"code": "315", "parentCode": "31", "level": "3", "name": "Skipoffiserer, flygere, flygeledere mv."},
    {"code": "3154", "parentCode": "315", "level": "4", "name": "Flygeledere"},
    {"code": "1", "parentCode": None, "level": "1", "name": "Ledere"},
    {"code": "11", "parentCode": "1", "level": "2", "name": "Politikere og toppledere"},
    {"code": "111", "parentCode": "11", "level": "3", "name": "Politikere"},
    {"code": "1111", "parentCode": "111", "level": "4", "name": "Politikere"},
]


def _dim(koder: list[str], navn: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "category": {
            "index": {k: i for i, k in enumerate(koder)},
            "label": {k: (navn or {}).get(k, k) for k in koder},
        }
    }


def _doc(dimensjoner: dict[str, dict[str, Any]], verdier: list[Any]) -> dict[str, Any]:
    ids = list(dimensjoner)
    size = [len(d["category"]["index"]) for d in dimensjoner.values()]
    return {
        "class": "dataset",
        "label": "Oppdiktet lønnstabell",
        "updated": "2026-08-13T06:00:00Z",
        "id": ids,
        "size": size,
        "dimension": dimensjoner,
        "value": verdier,
    }


def _lonn_aar_doc() -> dict[str, Any]:
    yrker = [YRKE, DEKOY]
    aar = ["2015", "2016", "2017"]
    verdier = [LONN_AAR[y][a] for y in yrker for a in aar]
    return _doc(
        {
            "MaaleMetode": _dim(["01"], {"01": "Median"}),
            "Yrke": _dim(yrker),
            "Sektor": _dim(["ALLE"], {"ALLE": "Sum alle sektorer"}),
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "AvtaltVanlig": _dim(["0"], {"0": "I alt"}),
            "ContentsCode": _dim(["Manedslonn"]),
            "Tid": _dim(aar),
        },
        verdier,
    )


def _lonn_kvartal_doc() -> dict[str, Any]:
    yrker = [YRKE, DEKOY]
    kvartal = ["2016K1", "2016K2", "2017K1"]
    verdier = [LONN_KVARTAL[y][k] for y in yrker for k in kvartal]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(yrker),
            "ContentsCode": _dim(["MedianMndLonn"]),
            "Tid": _dim(kvartal),
        },
        verdier,
    )


def _kvartal_doc() -> dict[str, Any]:
    yrker = [YRKE, DEKOY]
    kvartal = ["2016K1", "2016K2", "2017K1"]
    verdier = [BESTAND[y][k] for y in yrker for k in kvartal]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(yrker, {YRKE: "Flygeledere", DEKOY: "Politikere"}),
            "ContentsCode": _dim(["Lonsstakere"]),
            "Tid": _dim(kvartal),
        },
        verdier,
    )


def _kpi_doc() -> dict[str, Any]:
    maaneder = sorted(KPI)
    return _doc(
        {
            "VareTjenesteGrp": _dim(["00"], {"00": "I alt"}),
            "ContentsCode": _dim(["KpiIndMnd"]),
            "Tid": _dim(maaneder),
        },
        [KPI[m] for m in maaneder],
    )


def _skriv_raa() -> None:
    for dataset, doc in (
        ("11418_lonn_aar", _lonn_aar_doc()),
        ("11658_lonn_kvartal", _lonn_kvartal_doc()),
        ("11658_kvartal", _kvartal_doc()),
        ("14700_kpi", _kpi_doc()),
    ):
        io.write_raw("ssb", dataset, json.dumps(doc).encode("utf-8"), {"license": "test"})
    io.write_raw(
        "klass",
        "styrk08_codes",
        json.dumps({"codes": KLASS_KODER}).encode("utf-8"),
        {"license": "test"},
        suffix="json",
    )


@pytest.fixture
def built(project) -> dict[str, registry.BuildResult]:
    _skriv_raa()
    return {
        r.name: r
        for r in registry.build(["mart.flygeledere_lonn", "mart.flygeledere_bestand_siste"])
    }


def _rad(kilde: str, periode: str):
    import polars as pl

    df = io.load("mart.flygeledere_lonn")
    treff = df.filter((pl.col("kilde") == kilde) & (pl.col("periode") == periode))
    assert treff.height == 1, (kilde, periode, treff.height)
    return treff.row(0, named=True)


# --------------------------------------------------------------------------
def test_build_covers_the_chain(built: dict[str, registry.BuildResult]) -> None:
    assert set(built) >= {"mart.flygeledere_lonn"}


def test_only_the_one_occupation_is_kept(built: dict[str, registry.BuildResult]) -> None:
    """1111 er med i rådata for å bevise at filteret faktisk filtrerer."""
    df = io.load("mart.flygeledere_lonn")
    assert set(df["yrke"].to_list()) == {YRKE}
    assert df.height == 4  # 2 årlige (2016 undertrykt) + 2 kvartalsvise (2016K1 undertrykt)


def test_suppressed_points_are_simply_absent_not_zero_or_interpolated(
    built: dict[str, registry.BuildResult],
) -> None:
    """Kildens undertrykte punkter skal ikke finnes som rad i det hele tatt.

    Verken som 0, som et interpolert tall, eller som en rad andre kan lese
    som en manglende måling forkledd som en ekte. Det er selve mekanismen
    bak det ekte 2021-2024-hullet for flygeledere.
    """
    df = io.load("mart.flygeledere_lonn")
    assert df.filter(
        (df["kilde"] == "aarlig") & (df["periode"] == "2016")
    ).height == 0
    assert df.filter(
        (df["kilde"] == "kvartalsvis") & (df["periode"] == "2016K1")
    ).height == 0


def test_the_two_sources_are_never_merged_into_one_row(
    built: dict[str, registry.BuildResult],
) -> None:
    """Grainet er (kilde, periode) — to kilder samme år er to rader, ikke én."""
    df = io.load("mart.flygeledere_lonn")
    assert sorted(zip(df["kilde"].to_list(), df["periode"].to_list())) == [
        ("aarlig", "2015"),
        ("aarlig", "2017"),
        ("kvartalsvis", "2016K2"),
        ("kvartalsvis", "2017K1"),
    ]


def test_annual_points_deflate_with_november_that_year(
    built: dict[str, registry.BuildResult],
) -> None:
    rad = _rad("aarlig", "2015")
    assert rad["kpi_referanse"] == pytest.approx(KPI["2015M11"])
    assert rad["median_lonn_nominell"] == pytest.approx(80_000.0)
    assert rad["median_lonn_realt"] == pytest.approx(80_000.0 * KPI["2025M11"] / KPI["2015M11"])


def test_quarterly_points_deflate_with_the_three_month_average(
    built: dict[str, registry.BuildResult],
) -> None:
    rad = _rad("kvartalsvis", "2016K2")
    snitt = (KPI["2016M04"] + KPI["2016M05"] + KPI["2016M06"]) / 3
    assert rad["kpi_referanse"] == pytest.approx(snitt)
    assert rad["median_lonn_realt"] == pytest.approx(90_200.0 * KPI["2025M11"] / snitt)


def test_both_sources_share_the_same_deflation_basis(
    built: dict[str, registry.BuildResult],
) -> None:
    """Uten en felles referanse ville et bytte av kilde sett ut som en lønnsendring."""
    aarlig = _rad("aarlig", "2017")
    kvartalsvis = _rad("kvartalsvis", "2017K1")
    basis_aarlig = aarlig["median_lonn_realt"] / aarlig["median_lonn_nominell"] * aarlig["kpi_referanse"]
    basis_kvartalsvis = (
        kvartalsvis["median_lonn_realt"] / kvartalsvis["median_lonn_nominell"] * kvartalsvis["kpi_referanse"]
    )
    assert basis_aarlig == pytest.approx(basis_kvartalsvis)
    assert basis_aarlig == pytest.approx(KPI["2025M11"])


def test_periode_x_places_annual_points_in_november_and_quarterly_points_within_the_quarter(
    built: dict[str, registry.BuildResult],
) -> None:
    assert _rad("aarlig", "2015")["periode_x"] == pytest.approx(2015 + 10 / 12)
    assert _rad("kvartalsvis", "2016K2")["periode_x"] == pytest.approx(2016 + 0.25 + 0.125)
    assert _rad("kvartalsvis", "2017K1")["periode_x"] == pytest.approx(2017 + 0.125)
    # Innenfor samme år ligger kvartalspunktene i stigende rekkefølge.
    assert _rad("kvartalsvis", "2017K1")["periode_x"] < _rad("aarlig", "2017")["periode_x"]


def test_occupation_name_comes_from_klass(built: dict[str, registry.BuildResult]) -> None:
    assert _rad("aarlig", "2015")["yrke_navn"] == "Flygeledere"


# --------------------------------------------------------------------------
# mart.flygeledere_bestand_siste
# --------------------------------------------------------------------------
def test_bestand_picks_the_newest_quarter_that_actually_exists(
    built: dict[str, registry.BuildResult],
) -> None:
    """2017K1 mangler i kilden for YRKE — den skal ikke telle som «nyeste»."""
    df = io.load("mart.flygeledere_bestand_siste")
    assert df.height == 1
    rad = df.row(0, named=True)
    assert rad["kvartal"] == "2016K2"
    assert rad["lonnstakere"] == BESTAND[YRKE]["2016K2"]
    assert rad["yrke_navn"] == "Flygeledere"
