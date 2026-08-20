"""Arbeidsmarkedet, yrke for yrke — clean- og mart-laget.

Kilden er oppdiktet, men formen er den ekte: json-stat2 fra SSBs tabell
11658 og 14789, og et KLASS-svar for STYRK-08. Universet er lite nok til at
hvert tall kan regnes i hodet, og satt opp slik at hver av de vanskelige
tilfellene finnes én gang:

* et yrke som er for lite i starten av perioden (5112),
* et yrke i hovedgruppe 0, som ikke tåler en tidsserie (0000),
* en medianlønn på 0, som er kildens måte å si «ingen å regne på» (5112),
* en snittalder og en arbeidstid på 0, som betyr det samme (0000 i
  startkvartalet),
* en årlig serie som ikke rekker fram til siste årspunkt (sykefraværet),
* en hovedgruppe tabellen ikke navngir, men KLASS gjør (0 og 1).
"""

from __future__ import annotations

import json
from typing import Any

import polars as pl
import pytest

from statman import io, registry

# Fire yrker, tre hovedgrupper, pluss kildens egen totalkode.
YRKER: list[str] = ["0-9", "1111", "5111", "5112", "0000"]
FIRESIDE: list[str] = ["1111", "5111", "5112", "0000"]
YRKESNAVN: dict[str, str] = {
    "0-9": "Alle yrker",
    "1111": "Politikere",
    "5111": "Butikkmedarbeidere",
    "5112": "Pantelånere mv.",
    "0000": "Uoppgitt / yrker som ikke kan identifiseres",
}

KVARTAL: list[str] = ["2016K2", "2026K2"]

# Bestand per yrke, [start, slutt]. De fireside summerer seg til totalen i
# begge ender — det er nettopp den egenskapen mart-laget sjekker.
BESTAND: dict[str, list[int]] = {
    "0-9": [10_000, 12_000],
    "1111": [1_000, 2_000],     # vokser 100 %, stor nok i begge ender
    "5111": [8_000, 9_000],     # vokser 12,5 %
    "5112": [400, 800],         # for liten i starten
    "0000": [600, 200],         # hovedgruppe 0
}

# Siste kvartal: lønn, alder, arbeidstid. 5112 har medianlønn 0 — kildens
# markering for at det ikke er noen å regne median for.
#
# Lønna er den samme som LONN_KVARTAL har i sluttkvartalet, og må være det:
# hos SSB er de to uttrekkene den samme variabelen fra den samme tabellen,
# og et oppdiktet univers der de spriker ville skjult at årstabellen og
# øyeblikksbildet skal måle det samme. Sjekken står i
# test_the_fixture_agrees_with_itself_about_the_last_wage.
SISTE: dict[str, list[float]] = {
    #        lønn,   alder, arbeidstid
    "0-9": [60_000, 42.0, 34.0],
    "1111": [80_000, 47.5, 15.9],
    "5111": [50_000, 38.2, 30.1],
    "5112": [0, 44.5, 26.3],
    "0000": [55_000, 41.0, 19.2],
}

# Kvinner og menn per yrke, siste kvartal. Summerer til bestanden.
KJONN: dict[str, tuple[int, int]] = {
    "0-9": (6_000, 6_000),
    "1111": (900, 1_100),
    "5111": (5_000, 4_000),
    "5112": (60, 740),
    "0000": (40, 160),
}
LONN_KJONN: dict[str, tuple[float, float]] = {
    "0-9": (48_000, 52_000),
    "1111": (86_000, 90_000),
    "5111": (41_000, 43_000),
    "5112": (0, 0),
    "0000": (42_000, 45_000),
}

# Kjønnsdelingen i begge kvartaler. Slutten er den samme som KJONN, så
# øyeblikksbildet og årstabellen skal gi nøyaktig samme kvinneandel i det
# siste punktet — det er en av sjekkene under.
KJONN_KVARTAL: dict[str, list[tuple[int, int]]] = {
    "0-9": [(5_000, 5_000), KJONN["0-9"]],
    "1111": [(400, 600), KJONN["1111"]],
    "5111": [(4_400, 3_600), KJONN["5111"]],
    "5112": [(100, 300), KJONN["5112"]],
    "0000": [(200, 400), KJONN["0000"]],
}

# Snittalder og avtalt arbeidstid i begge kvartaler, samme mønster. 0000 har
# 0 i starten: kildens måte å si at det ikke er noen å regne gjennomsnitt
# over, og det skal bli null i mart — ikke en snittalder på null år.
TREKK_KVARTAL: dict[str, list[tuple[float, float]]] = {
    "0-9": [(40.0, 35.0), (SISTE["0-9"][1], SISTE["0-9"][2])],
    "1111": [(45.0, 16.5), (SISTE["1111"][1], SISTE["1111"][2])],
    "5111": [(36.0, 31.5), (SISTE["5111"][1], SISTE["5111"][2])],
    "5112": [(42.0, 27.0), (SISTE["5112"][1], SISTE["5112"][2])],
    "0000": [(0.0, 0.0), (SISTE["0000"][1], SISTE["0000"][2])],
}

# Tre aldersbånd som summerer til bestanden.
ALDER: dict[str, tuple[int, int, int]] = {
    "0-9": (5_000, 4_000, 3_000),
    "1111": (500, 800, 700),
    "5111": (4_000, 3_000, 2_000),
    "5112": (400, 200, 200),
    "0000": (100, 60, 40),
}

# Medianlønn i hver ende. 1111 får reallønnsvekst (nominelt +60 % mot 33 %
# prisvekst), 5111 får reallønnsfall (+25 %). 5112 er kildens 0.
LONN_KVARTAL: dict[str, list[float]] = {
    "0-9": [45_000, 60_000],
    "1111": [50_000, 80_000],
    "5111": [40_000, 50_000],
    "5112": [0, 0],
    "0000": [43_000, 55_000],
}

# KPI: 75 gjennom hele 2016, 100 gjennom hele 2026, lineært imellom. Da er
# prisveksten nøyaktig 33,33 prosent, og deflatoren for 2016K2 er 4/3.
#
# Serien stopper i august, som den ekte gjør: KPI publiseres månedlig og
# ligger foran kvartalsstatistikken. Det gir ett ufullstendig kvartal
# (2026K3 med to måneder) som skal falle ut, og et referansekvartal som er
# det siste fullstendige — 2026K2.
KPI_START_AAR: int = 2016
KPI_SLUTT_AAR: int = 2026
KPI_SISTE_MAANED: int = 8
KPI_START: float = 75.0
KPI_SLUTT: float = 100.0

# Tre år, så vi kan sjekke at mart tar det siste. 0000 mangler helt.
#
# 2016 er med og 2026 er ikke: sykefraværet er årlig og ligger etter
# kvartalsstatistikken, akkurat som i den ekte kilden. Det gir en serie som
# rekker fram til det første årspunktet og ikke lenger — og det er den
# egenskapen tidslinja må kunne oppgi.
SYKEFRAVAER_AAR: list[str] = ["2016", "2024", "2025"]
SYKEFRAVAER: dict[str, dict[str, float]] = {
    "0-9": {"2016": 4.6, "2024": 5.0, "2025": 5.4},
    "1111": {"2016": 1.8, "2024": 2.0, "2025": 2.2},
    "5111": {"2016": 5.5, "2024": 6.0, "2025": 6.6},
    "5112": {"2016": 3.7, "2024": 4.0, "2025": 4.4},
}

KLASS_KODER: list[dict[str, Any]] = [
    {"code": "0", "parentCode": None, "level": "1", "name": "Militære yrker og uoppgitt"},
    {"code": "00", "parentCode": "0", "level": "2", "name": "Uoppgitt"},
    {"code": "000", "parentCode": "00", "level": "3", "name": "Uoppgitt"},
    {"code": "0000", "parentCode": "000", "level": "4", "name": YRKESNAVN["0000"]},
    {"code": "1", "parentCode": None, "level": "1", "name": "Ledere"},
    {"code": "11", "parentCode": "1", "level": "2", "name": "Politikere og toppledere"},
    {"code": "111", "parentCode": "11", "level": "3", "name": "Politikere"},
    {"code": "1111", "parentCode": "111", "level": "4", "name": YRKESNAVN["1111"]},
    {"code": "5", "parentCode": None, "level": "1", "name": "Salgs- og serviceyrker"},
    {"code": "51", "parentCode": "5", "level": "2", "name": "Salgsyrker"},
    {"code": "511", "parentCode": "51", "level": "3", "name": "Butikk"},
    {"code": "5111", "parentCode": "511", "level": "4", "name": YRKESNAVN["5111"]},
    {"code": "5112", "parentCode": "511", "level": "4", "name": YRKESNAVN["5112"]},
]


# --------------------------------------------------------------------------
# json-stat2-dokumenter
# --------------------------------------------------------------------------
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
        "label": "Oppdiktet yrkestabell",
        "updated": "2026-08-13T06:00:00Z",
        "id": ids,
        "size": size,
        "dimension": dimensjoner,
        "value": verdier,
    }


def _kvartal_doc() -> dict[str, Any]:
    # Kjonn × Alder × Yrke × ContentsCode × Tid, row-major.
    verdier = [BESTAND[y][t] for y in YRKER for t in range(len(KVARTAL))]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["Lonsstakere"]),
            "Tid": _dim(KVARTAL),
        },
        verdier,
    )


def _siste_doc() -> dict[str, Any]:
    verdier: list[Any] = []
    for y in YRKER:
        lonn, alder, tid = SISTE[y]
        verdier += [BESTAND[y][-1], lonn, alder, tid]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(
                ["Lonsstakere", "MedianMndLonn", "GjsnAlder", "GjAvtArbtid"]
            ),
            "Tid": _dim([KVARTAL[-1]]),
        },
        verdier,
    )


def _kjonn_doc() -> dict[str, Any]:
    verdier: list[Any] = []
    for i in (0, 1):  # kvinner, så menn
        for y in YRKER:
            verdier += [KJONN[y][i], LONN_KJONN[y][i]]
    return _doc(
        {
            "Kjonn": _dim(["2", "1"], {"2": "Kvinner", "1": "Menn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["Lonsstakere", "MedianMndLonn"]),
            "Tid": _dim([KVARTAL[-1]]),
        },
        verdier,
    )


def _alder_doc() -> dict[str, Any]:
    bånd = ["0-39", "40-54", "55+"]
    verdier = [ALDER[y][i] for i in range(len(bånd)) for y in YRKER]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(bånd),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["Lonsstakere"]),
            "Tid": _dim([KVARTAL[-1]]),
        },
        verdier,
    )


def _sykefravaer_doc() -> dict[str, Any]:
    aar = SYKEFRAVAER_AAR
    verdier = [SYKEFRAVAER.get(y, {}).get(a) for y in YRKER for a in aar]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["Sykefraversprosent"]),
            "Tid": _dim(aar),
        },
        verdier,
    )


def _kjonn_kvartal_doc() -> dict[str, Any]:
    verdier: list[Any] = []
    for i in (0, 1):  # kvinner, så menn
        for y in YRKER:
            verdier += [KJONN_KVARTAL[y][t][i] for t in range(len(KVARTAL))]
    return _doc(
        {
            "Kjonn": _dim(["2", "1"], {"2": "Kvinner", "1": "Menn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["Lonsstakere"]),
            "Tid": _dim(KVARTAL),
        },
        verdier,
    )


def _trekk_kvartal_doc() -> dict[str, Any]:
    verdier: list[Any] = []
    for y in YRKER:
        for i in (0, 1):  # GjsnAlder, så GjAvtArbtid
            verdier += [TREKK_KVARTAL[y][t][i] for t in range(len(KVARTAL))]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["GjsnAlder", "GjAvtArbtid"]),
            "Tid": _dim(KVARTAL),
        },
        verdier,
    )


def _kpi_maaneder() -> list[str]:
    return [
        f"{aar}M{mnd:02d}"
        for aar in range(KPI_START_AAR, KPI_SLUTT_AAR + 1)
        for mnd in range(1, 13)
        if not (aar == KPI_SLUTT_AAR and mnd > KPI_SISTE_MAANED)
    ]


def _lonn_kvartal_doc() -> dict[str, Any]:
    verdier = [LONN_KVARTAL[y][t] for y in YRKER for t in range(len(KVARTAL))]
    return _doc(
        {
            "Kjonn": _dim(["0"], {"0": "Begge kjønn"}),
            "Alder": _dim(["999D"], {"999D": "Alle aldre"}),
            "Yrke": _dim(YRKER, YRKESNAVN),
            "ContentsCode": _dim(["MedianMndLonn"]),
            "Tid": _dim(KVARTAL),
        },
        verdier,
    )


def _kpi_doc() -> dict[str, Any]:
    maaneder = _kpi_maaneder()
    spenn = KPI_SLUTT_AAR - KPI_START_AAR
    verdier = [
        KPI_START + (KPI_SLUTT - KPI_START) * (int(m[:4]) - KPI_START_AAR) / spenn
        for m in maaneder
    ]
    return _doc(
        {
            "VareTjenesteGrp": _dim(["00"], {"00": "I alt"}),
            "ContentsCode": _dim(["KpiIndMnd"]),
            "Tid": _dim(maaneder),
        },
        verdier,
    )


def _skriv_raa() -> None:
    for dataset, doc in (
        ("11658_kvartal", _kvartal_doc()),
        ("11658_lonn_kvartal", _lonn_kvartal_doc()),
        ("14700_kpi", _kpi_doc()),
        ("11658_siste", _siste_doc()),
        ("11658_kjonn", _kjonn_doc()),
        ("11658_alder", _alder_doc()),
        ("11658_kjonn_kvartal", _kjonn_kvartal_doc()),
        ("11658_trekk_kvartal", _trekk_kvartal_doc()),
        ("14789_sykefravaer", _sykefravaer_doc()),
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
    targets = [
        "mart.arbeidsmarked_yrke",
        "mart.arbeidsmarked_yrke_aar",
        "mart.arbeidsmarked_hovedgruppe_kvartal",
        "mart.arbeidsmarked_reallonn_gruppe",
    ]
    return {r.name: r for r in registry.build(targets)}


def _yrke(built: dict[str, registry.BuildResult], kode: str) -> dict[str, Any]:
    df = io.load("mart.arbeidsmarked_yrke")
    return df.filter(pl.col("yrke") == kode).row(0, named=True)


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------
def test_build_covers_the_whole_chain(built: dict[str, registry.BuildResult]) -> None:
    assert set(built) == {
        "clean.styrk",
        "clean.yrke_kvartal",
        "clean.yrke_siste",
        "clean.yrke_kjonn",
        "clean.yrke_kjonn_kvartal",
        "clean.yrke_trekk_kvartal",
        "clean.yrke_alder",
        "clean.yrke_sykefravaer",
        "clean.yrke_lonn_kvartal",
        "clean.konsumprisindeks",
        "mart.konsumpris_kvartal",
        "mart.arbeidsmarked_lonn_kvartal",
        "mart.arbeidsmarked_yrke",
        "mart.arbeidsmarked_yrke_aar",
        "mart.arbeidsmarked_hovedgruppe_kvartal",
        "mart.arbeidsmarked_reallonn_gruppe",
    }


def test_clean_keeps_every_code_level(built: dict[str, registry.BuildResult]) -> None:
    """clean velger ikke nivå. Totalkoden må være der for mart å sjekke mot."""
    koder = set(io.load("clean.yrke_kvartal")["yrke"].to_list())
    assert koder == set(YRKER)


def test_clean_keeps_the_sources_zero_median(built: dict[str, registry.BuildResult]) -> None:
    """En 0 fra kilden er kildens tall. Å tolke den er mart-lagets jobb."""
    df = io.load("clean.yrke_siste")
    rad = df.filter((pl.col("yrke") == "5112") & (pl.col("variabel") == "medianmndlonn"))
    assert rad.row(0, named=True)["verdi"] == 0.0


def test_styrk_is_a_tree(built: dict[str, registry.BuildResult]) -> None:
    styrk = io.load("clean.styrk")
    assert styrk.height == len(KLASS_KODER)
    # Hver kode på nivå n har en forelder på nivå n-1, og bare nivå 1 har ingen.
    etter_kode = {r["kode"]: r for r in styrk.iter_rows(named=True)}
    for rad in styrk.iter_rows(named=True):
        if rad["nivaa"] == 1:
            assert rad["forelder"] is None
        else:
            assert etter_kode[rad["forelder"]]["nivaa"] == rad["nivaa"] - 1


# --------------------------------------------------------------------------
# mart — grain og partisjon
# --------------------------------------------------------------------------
def test_mart_has_one_row_per_four_digit_occupation(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.arbeidsmarked_yrke")
    assert sorted(df["yrke"].to_list()) == sorted(FIRESIDE)


def test_the_four_digit_codes_partition_the_total(
    built: dict[str, registry.BuildResult],
) -> None:
    """Flisediagrammets grunnforutsetning, i begge ender av perioden.

    Er summen bare omtrent totalen, påstår figuren å være helheten uten å
    være det — og den ser like riktig ut.
    """
    df = io.load("mart.arbeidsmarked_yrke")
    assert df["lonnstakere"].sum() == BESTAND["0-9"][-1]
    assert df["lonnstakere_start"].sum() == BESTAND["0-9"][0]


def test_group_names_come_from_klass_not_the_table(
    built: dict[str, registry.BuildResult],
) -> None:
    """Tabellen navngir ikke hovedgruppe 0 og 3. Standarden gjør."""
    assert _yrke(built, "0000")["hovedgruppe_navn"] == "Militære yrker og uoppgitt"
    assert _yrke(built, "1111")["hovedgruppe_navn"] == "Ledere"
    assert _yrke(built, "1111")["yrkesgruppe_navn"] == "Politikere og toppledere"


# --------------------------------------------------------------------------
# mart — valgene
# --------------------------------------------------------------------------
def test_a_zero_median_is_not_a_wage(built: dict[str, registry.BuildResult]) -> None:
    """Kildens 0 betyr «ingen å regne på», og må ikke bli med i en topplista."""
    assert _yrke(built, "5112")["median_lonn"] is None
    assert _yrke(built, "5112")["median_lonn_kvinner"] is None
    assert _yrke(built, "5111")["median_lonn"] == SISTE["5111"][0]


def test_growth_is_measured_between_the_same_quarter_ten_years_apart(
    built: dict[str, registry.BuildResult],
) -> None:
    rad = _yrke(built, "1111")
    assert rad["kvartal_start"] == "2016K2"
    assert rad["kvartal_slutt"] == "2026K2"
    assert rad["lonnstakere_start"] == 1_000
    assert rad["vekst_antall"] == 1_000
    assert rad["vekst_pst"] == pytest.approx(1.0)


def test_small_occupations_are_kept_but_not_ranked(
    built: dict[str, registry.BuildResult],
) -> None:
    """Under terskelen flytter én arbeidsgiver prosenten mer enn markedet.

    Yrket skal likevel bli stående i tabellen — det er en del av
    arbeidsmarkedet, det er bare ikke noe å rangere.
    """
    rad = _yrke(built, "5112")
    assert rad["sammenlignbar"] is False
    assert rad["lonnstakere"] == 800
    assert rad["vekst_pst"] == pytest.approx(1.0)


def test_the_military_group_is_never_comparable(
    built: dict[str, registry.BuildResult],
) -> None:
    """Hovedgruppe 0 er en omkoding og en restkategori, ikke et arbeidsmarked."""
    rad = _yrke(built, "0000")
    assert rad["lonnstakere"] >= 200
    assert rad["sammenlignbar"] is False


def test_a_large_enough_occupation_is_comparable(
    built: dict[str, registry.BuildResult],
) -> None:
    assert _yrke(built, "5111")["sammenlignbar"] is True
    assert _yrke(built, "1111")["sammenlignbar"] is True


def test_sex_and_age_split_the_same_population(
    built: dict[str, registry.BuildResult],
) -> None:
    for kode in FIRESIDE:
        rad = _yrke(built, kode)
        assert rad["kvinner"] + rad["menn"] == rad["lonnstakere"]
        assert rad["under_40"] + rad["fra_40_til_54"] + rad["fra_55"] == rad["lonnstakere"]


def test_shares_are_computed_on_the_full_population(
    built: dict[str, registry.BuildResult],
) -> None:
    rad = _yrke(built, "5111")
    assert rad["kvinneandel"] == pytest.approx(5_000 / 9_000)
    assert rad["andel_55plus"] == pytest.approx(2_000 / 9_000)


def test_sick_leave_takes_the_latest_year_and_may_be_missing(
    built: dict[str, registry.BuildResult],
) -> None:
    rad = _yrke(built, "5111")
    assert rad["sykefravaer_aar"] == 2025
    assert rad["sykefravaer_pst"] == pytest.approx(6.6)
    # 0000 har ingen rad i kilden, og skal da være null — ikke null prosent.
    assert _yrke(built, "0000")["sykefravaer_pst"] is None


# --------------------------------------------------------------------------
# mart — hovedgruppene over tid
# --------------------------------------------------------------------------
def test_group_series_is_a_rollup_of_the_occupations(
    built: dict[str, registry.BuildResult],
) -> None:
    """Summert opp fra yrkene, fordi kildens ensifrede nivå ikke er komplett."""
    df = io.load("mart.arbeidsmarked_hovedgruppe_kvartal")
    assert set(df["hovedgruppe"].to_list()) == {"0", "1", "5"}
    for kvartal, i in (("2016K2", 0), ("2026K2", 1)):
        total = df.filter(pl.col("kvartal") == kvartal)["lonnstakere"].sum()
        assert total == BESTAND["0-9"][i]
    salg = df.filter((pl.col("hovedgruppe") == "5") & (pl.col("kvartal") == "2026K2"))
    assert salg.row(0, named=True)["lonnstakere"] == 9_000 + 800


# --------------------------------------------------------------------------
# mart — deflatering og reallønn
# --------------------------------------------------------------------------
def test_quarterly_kpi_is_the_mean_of_three_months(
    built: dict[str, registry.BuildResult],
) -> None:
    kpi = io.load("mart.konsumpris_kvartal")
    assert kpi.filter(pl.col("maaneder") != 3).height == 0
    start = kpi.filter(pl.col("kvartal") == "2016K2").row(0, named=True)
    assert start["kpi"] == pytest.approx(KPI_START)
    assert start["kvartal_referanse"] == "2026K2"
    # Deflatoren for referansekvartalet er per definisjon 1.
    siste = kpi.filter(pl.col("kvartal") == "2026K2").row(0, named=True)
    assert siste["deflator_siste"] == pytest.approx(1.0)
    assert start["deflator_siste"] == pytest.approx(KPI_SLUTT / KPI_START)


def test_incomplete_quarters_are_dropped(built: dict[str, registry.BuildResult]) -> None:
    """Et kvartal med én publisert måned ville gitt den måneden som «snitt».

    KPI ligger foran lønnsstatistikken, så det siste kvartalet er ofte
    ufullstendig. Deflaterer man med det, ser prisnivået feil ut og
    differansen leses som reallønn.
    """
    kpi = io.load("mart.konsumpris_kvartal")
    kvartaler = kpi["kvartal"].to_list()
    # 2026K3 har bare juli og august i kilden, og skal ikke finnes her.
    assert "2026K2" in kvartaler
    assert "2026K3" not in kvartaler
    assert kpi.height == io.load("clean.konsumprisindeks").height // 3


def test_real_wage_is_nominal_deflated_to_the_reference_quarter(
    built: dict[str, registry.BuildResult],
) -> None:
    serie = io.load("mart.arbeidsmarked_lonn_kvartal")
    start = serie.filter((pl.col("yrke") == "1111") & (pl.col("kvartal") == "2016K2")).row(
        0, named=True
    )
    assert start["median_lonn_nominell"] == pytest.approx(LONN_KVARTAL["1111"][0])
    assert start["median_lonn_realt"] == pytest.approx(
        LONN_KVARTAL["1111"][0] * KPI_SLUTT / KPI_START
    )
    # I referansekvartalet er de to like.
    slutt = serie.filter((pl.col("yrke") == "1111") & (pl.col("kvartal") == "2026K2")).row(
        0, named=True
    )
    assert slutt["median_lonn_realt"] == pytest.approx(slutt["median_lonn_nominell"])


def test_a_zero_median_never_reaches_the_real_wage_series(
    built: dict[str, registry.BuildResult],
) -> None:
    """Deflatert er null fortsatt null, og ville blitt et punkt i bunnen."""
    serie = io.load("mart.arbeidsmarked_lonn_kvartal")
    assert serie.filter(pl.col("yrke") == "5112").height == 0


def test_real_growth_is_below_nominal_when_prices_rose(
    built: dict[str, registry.BuildResult],
) -> None:
    rad = _yrke(built, "1111")
    # +60 % nominelt mot 33,3 % prisvekst.
    assert rad["lonn_vekst_pst"] == pytest.approx(0.6)
    assert rad["reallonn_vekst_pst"] == pytest.approx(1.6 / (KPI_SLUTT / KPI_START) - 1)
    assert rad["reallonn_vekst_pst"] < rad["lonn_vekst_pst"]


def test_nominal_growth_below_inflation_is_a_real_cut(
    built: dict[str, registry.BuildResult],
) -> None:
    """+25 prosent lønn mot 33 prosent prisvekst er et kutt, ikke et påslag."""
    rad = _yrke(built, "5111")
    assert rad["lonn_vekst_pst"] == pytest.approx(0.25)
    assert rad["reallonn_vekst_pst"] < 0


def test_the_break_quarter_is_measured_not_asserted(
    built: dict[str, registry.BuildResult],
) -> None:
    """Fixturen har ingen bruddkvartaler, så kolonnen skal være null.

    Poenget med kolonnen er at den er *målt*: finnes ikke kvartalene, står
    det ingenting der — ikke null, som ville betydd «ingen endring».
    """
    assert _yrke(built, "1111")["endring_bruddkvartal"] is None


def test_the_real_wage_index_uses_fixed_weights(
    built: dict[str, registry.BuildResult],
) -> None:
    """Indeksen skal måle lønn, ikke at sammensetningen endret seg.

    5111 er fire ganger større enn 1111 ved start og vokser mindre. Med
    løpende vekter ville gruppa 5 fått en annen bane; med faste vekter er
    den bestemt av lønnsendringen alene.
    """
    g = io.load("mart.arbeidsmarked_reallonn_gruppe")
    assert set(g["hovedgruppe"].to_list()) == {"0", "1", "5", "alle"}
    basis = g.filter(pl.col("kvartal") == "2016K2")
    assert basis["reallonn_indeks"].to_list() == pytest.approx([100.0] * basis.height)
    # 1111 er alene i hovedgruppe 1, så indeksen er yrkets egen reallønn.
    en = g.filter((pl.col("hovedgruppe") == "1") & (pl.col("kvartal") == "2026K2")).row(
        0, named=True
    )
    assert en["reallonn_indeks"] == pytest.approx(
        1.6 / (KPI_SLUTT / KPI_START) * 100
    )
    assert en["lonnstakere_vekt"] == BESTAND["1111"][0]


def test_an_empty_model_cannot_pass_its_checks(project) -> None:
    """En modell som lager null rader består alle radvise sjekker.

    Det er ikke teoretisk: kvartalsuttrykket i mart.konsumpris_kvartal ga
    tom tabell under utviklingen, og hver eneste sjekk passerte.
    """
    import duckdb

    from statman.registry import CheckFailed, run_checks

    con = duckdb.connect()
    path = io.data_dir() / "tom.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"copy (select 1 as a where false) to '{path.as_posix()}' (format parquet)"
    )
    # Radvise sjekker sier ingenting om en tom tabell.
    run_checks(con, "tom", path, ["not_null:a", "a > 0"])
    with pytest.raises(CheckFailed, match="0 rader"):
        run_checks(con, "tom", path, ["min_rows:1"])


# --------------------------------------------------------------------------
# mart.arbeidsmarked_yrke_aar — grunnlaget for tidslinja
# --------------------------------------------------------------------------
def _aar(built: dict[str, registry.BuildResult], kode: str, aar: int) -> dict[str, Any]:
    df = io.load("mart.arbeidsmarked_yrke_aar")
    return df.filter((pl.col("yrke") == kode) & (pl.col("aar") == aar)).row(0, named=True)


def test_the_year_table_has_one_row_per_occupation_and_point(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.arbeidsmarked_yrke_aar")
    assert df.height == len(FIRESIDE) * len(KVARTAL)
    assert sorted(df["aar"].unique().to_list()) == [int(k[:4]) for k in KVARTAL]
    # Totalkoden hører ikke hjemme her, like lite som i øyeblikksbildet.
    assert set(df["yrke"].to_list()) == set(FIRESIDE)


def test_every_year_point_sits_in_the_same_quarter(
    built: dict[str, registry.BuildResult],
) -> None:
    """Ellers måler en endring over serien delvis sesongsvingningen."""
    df = io.load("mart.arbeidsmarked_yrke_aar")
    kvartalsnr = {k[4:] for k in df["kvartal"].to_list()}
    assert kvartalsnr == {KVARTAL[-1][4:]}


def test_the_last_year_point_equals_the_snapshot(
    built: dict[str, registry.BuildResult],
) -> None:
    """Årstabellen og øyeblikksbildet måler det samme i det siste punktet.

    De kommer fra hver sine uttrekk — det ene over hele serien, det andre
    bare siste kvartal — og hvis de spriker, er ett av dem koblet på feil
    kvartal. Da ville figuren skiftet tall i det leseren rørte tidslinja.
    """
    siste = int(KVARTAL[-1][:4])
    for kode in FIRESIDE:
        snitt = _yrke(built, kode)
        punkt = _aar(built, kode, siste)
        assert punkt["lonnstakere"] == snitt["lonnstakere"]
        assert punkt["kvinneandel"] == snitt["kvinneandel"]
        assert punkt["median_lonn"] == snitt["median_lonn"]
        assert punkt["gjennomsnittsalder"] == snitt["gjennomsnittsalder"]
        assert punkt["avtalt_arbeidstid"] == snitt["avtalt_arbeidstid"]


def test_the_first_year_point_equals_the_snapshots_starting_stock(
    built: dict[str, registry.BuildResult],
) -> None:
    """Endringslaget skal gi nøyaktig den veksten saken selv oppgir."""
    forste = int(KVARTAL[0][:4])
    for kode in FIRESIDE:
        assert _aar(built, kode, forste)["lonnstakere"] == _yrke(built, kode)["lonnstakere_start"]


def test_a_zero_average_is_not_a_measurement(
    built: dict[str, registry.BuildResult],
) -> None:
    """Kildens 0 betyr «ingen å regne over», og skal bli null her.

    Uten dette havner yrket på det laveste trinnet i figuren — farget som
    «under 38 år», som om noen hadde talt.
    """
    raa = io.load("clean.yrke_trekk_kvartal").filter(
        (pl.col("yrke") == "0000") & (pl.col("kvartal") == KVARTAL[0])
    )
    assert sorted(raa["verdi"].to_list()) == [0.0, 0.0]

    punkt = _aar(built, "0000", int(KVARTAL[0][:4]))
    assert punkt["gjennomsnittsalder"] is None
    assert punkt["avtalt_arbeidstid"] is None
    # Og det samme i øyeblikksbildet, der kilden skriver 0.
    assert _yrke(built, "5112")["median_lonn"] is None


def test_sick_leave_does_not_reach_the_last_year_point(
    built: dict[str, registry.BuildResult],
) -> None:
    """Sykefraværet er årlig og ligger etter. Hullet skal bli stående.

    Å fylle det med fjorårets tall ville gjort en manglende måling til et
    datapunkt. Tidslinja oppgir i stedet hvor langt laget rekker.
    """
    df = io.load("mart.arbeidsmarked_yrke_aar")
    siste = int(KVARTAL[-1][:4])
    assert df.filter(pl.col("aar") == siste)["sykefravaer_pst"].null_count() == len(FIRESIDE)

    forste = int(KVARTAL[0][:4])
    assert _aar(built, "5111", forste)["sykefravaer_pst"] == SYKEFRAVAER["5111"]["2016"]
    # 0000 mangler i hele serien, og skal fortsatt mangle.
    assert _aar(built, "0000", forste)["sykefravaer_pst"] is None


def test_the_sexes_split_the_stock_in_every_point(
    built: dict[str, registry.BuildResult],
) -> None:
    """Sjekken som fanger en kjønnsserie koblet på feil kvartal."""
    df = io.load("mart.arbeidsmarked_yrke_aar")
    skjeve = df.filter(
        pl.col("kvinner").fill_null(0) + pl.col("menn").fill_null(0) != pl.col("lonnstakere")
    )
    assert skjeve.height == 0
    forste = _aar(built, "5111", int(KVARTAL[0][:4]))
    assert forste["kvinneandel"] == KJONN_KVARTAL["5111"][0][0] / BESTAND["5111"][0]


# --------------------------------------------------------------------------
# Tidslinja i sakspakken
# --------------------------------------------------------------------------
def test_declared_formats_match_the_packages_own_number_writing() -> None:
    """Lagenes format må skrive tallene som resten av sakspakken gjør.

    Formatene er en påstand om at sida og PNG-en sier det samme. Prøves den
    ikke, driver de fra hverandre uten at noe feiler — det var nettopp slik
    sykefraværet endte med å bli ganget med hundre én gang for mye.

    Halve siste siffer er ikke med: Python runder til nærmeste like tall,
    nettleserens Intl runder bort fra null, og 12,35 blir «12,3» i den ene
    og «12,4» i den andre. Ekte målinger har ikke flere desimaler enn dette
    uansett, og forskjellen er ett siffer i det minste sifferet.
    """
    from examples.arbeidsmarked_yrke import (
        FMT_AAR,
        FMT_ANDEL,
        FMT_ANTALL,
        FMT_ENDRING,
        FMT_KR,
        FMT_PROSENT,
        FMT_TIMER,
        _aar as _aar_tekst,
        _andel,
        _antall,
        _fravaer,
        _kr,
        _pst,
        _skriv,
        _timer,
    )

    par = (
        (FMT_KR, _kr, (42_120.0, 29_000.0, 75_500.0)),
        (FMT_ANTALL, _antall, (170_281.0, 500.0, 7.0)),
        (FMT_ENDRING, _pst, (0.0243452, -0.0589, 0.0, -0.00004, 0.2537)),
        (FMT_ANDEL, _andel, (0.60719, 0.0, 1.0)),
        (FMT_AAR, _aar_tekst, (35.8, 48.0)),
        (FMT_PROSENT, _fravaer, (5.6, 2.2)),
        (FMT_TIMER, _timer, (17.3, 37.5)),
    )
    for fmt, skriver, verdier in par:
        for verdi in verdier:
            assert _skriv(fmt, verdi) == skriver(verdi), (fmt, verdi)


def test_every_layer_declares_a_rule_a_scale_and_a_word_for_missing() -> None:
    """Uten alle tre kan ikke sida farge en flis den ikke har svaret på."""
    from statman.publish.article import RULES
    from examples.arbeidsmarked_yrke import LAG

    for lag in LAG:
        assert lag.regel in RULES, lag.key
        # Fem trinn krever fire grenser. Er de ute av takt, viser figuren
        # og tegnforklaringen hver sin inndeling.
        assert len(lag.grenser) == len(lag.roller) - 1, lag.key
        assert len(lag.tekster) == len(lag.roller), lag.key
        assert list(lag.grenser) == sorted(lag.grenser), lag.key
        assert lag.mangler_ord, lag.key
        # En nedre grense uten et ord for å ligge under den er en skravur
        # uten forklaring.
        assert (lag.gulv is None) == (not lag.under_ord), lag.key
        assert (lag.gulv is None) or lag.regel == "change", lag.key


def test_the_fixture_agrees_with_itself_about_the_last_wage() -> None:
    """De to lønnsuttrekkene er én variabel hos kilden, og må være det her."""
    for kode in YRKER:
        assert SISTE[kode][0] == LONN_KVARTAL[kode][-1], kode
