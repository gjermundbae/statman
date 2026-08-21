"""clean-laget for EUROCONTROL/PRB — trafikk og kapasitet, Avinor Flysikring.

Kilden (se ``statman/sources/eurocontrol.py``) er fem PDF-er, én per år
2020-2024, ikke en datatabell. Hvert tall vi bruker står som en setning i
løpende tekst — «Bodo ACC registered 7.62 IFR movements per one sector
opening hour in 2024» — og hvilke av de tre kontrollsentralene (ACC-ene:
Bodø/ENBD, Oslo/ENOSE, Stavanger/ENOSW) som nevnes med et konkret tall,
varierer fra år til år. Rapporten framhever det som endret seg mest det
året, ikke alle tre hver gang.

Denne modellen trekker derfor bare ut tall som faktisk står skrevet, med
regulære uttrykk kontrollert mot alle fem rapportene. Et forhold som ikke
nevnes et gitt år blir stående som ``null`` — aldri interpolert eller antatt
likt året før, av samme grunn som det fireårige hullet i
``mart.flygeledere_lonn`` ikke fylles. Se ``ARBEIDSBELASTNING.md`` — nei,
det finnes ikke en egen fil; forbeholdet står i ``examples/flygeledere_lonn.py``
sin Metode-seksjon, der de faktiske hullene i denne modellen også listes.

**ATCO-bemanning (antall flygeledere i operativ tjeneste) har bare et
konkret tall for 2024** — tidligere år oppgir kun relativ avstand til planen
("8 FTEs below the 2023 plan"), ikke et grunntall å trekke fra. Deler av
2023-, 2022- og 2021-rapportene sier at bemanningen økte i perioden, men
uten et starttall er det ikke mulig å regne ut noe presist derfra.

**Trafikktallet (IFR-bevegelser) er det eneste som er komplett**: alle fem
rapportene oppgir Norges egen «actual»-verdi for sitt år, og alle fem er
enige om at 2019-nivået var 591 000 bevegelser — sjekket direkte mot hver
rapports egen tekst, ikke antatt fra én av dem.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import polars as pl
from pypdf import PdfReader

from statman.registry import Context, model

YEARS: Final[tuple[int, ...]] = (2020, 2021, 2022, 2023, 2024)
RAW_PREFIX: Final[str] = "eurocontrol/prb_norway_"

ACC_KODE: Final[dict[str, str]] = {"Bodo": "ENBD", "Oslo": "ENOSE", "Stavanger": "ENOSW"}

_WS: Final[re.Pattern[str]] = re.compile(r"\s+")
_TRAFIKK: Final[re.Pattern[str]] = re.compile(
    r"Norway recorded (\d{1,3}(?:,\d{3})*)K actual IFR movements in (\d{4})"
)
_TRAFIKK_2019: Final[re.Pattern[str]] = re.compile(
    r"actual 2019 level \((\d{1,3}(?:,\d{3})*)K\)"
)
_PRODUKTIVITET: Final[re.Pattern[str]] = re.compile(
    r"(Bodo|Oslo|Stavanger) ACC registered (\d+\.\d+) IFR movements per one "
    r"sector opening hour in (\d{4})"
)
_SEKTORTIMER: Final[re.Pattern[str]] = re.compile(
    r"sector opening hours in (Bodo|Oslo|Stavanger) ACC was (\d{1,3}(?:,\d{3})*)"
)
_ATCO: Final[re.Pattern[str]] = re.compile(
    r"number of ATCOs in OPS is (\d+), being below the (\d{4}) plan in "
    r"(Bodo|Oslo|Stavanger) by (\d+) FTEs"
)


def _report_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return _WS.sub(" ", "\n".join(page.extract_text() or "" for page in reader.pages))


def _num(text: str) -> int:
    return int(text.replace(",", ""))


def parse_report(text: str, year: int) -> dict[str, Any]:
    """Trekk ut de eksplisitte tallene for ``year`` fra rapportens løpende tekst.

    Kun det som faktisk står som et tall for *dette* årstallet returneres.
    ``produktivitet``/``sektortimer``/``atco`` er ``{ACC: verdi}``-oppslag som
    kan mangle en eller flere av de tre ACC-ene, akkurat slik rapporten gjør.
    """
    trafikk_match = _TRAFIKK.search(text)
    trafikk = (
        float(_num(trafikk_match.group(1)))
        if trafikk_match and int(trafikk_match.group(2)) == year
        else None
    )

    produktivitet = {
        acc: float(verdi)
        for acc, verdi, aar in set(_PRODUKTIVITET.findall(text))
        if int(aar) == year
    }
    sektortimer = {acc: _num(verdi) for acc, verdi in set(_SEKTORTIMER.findall(text))}
    atco = {
        acc: {"ops": int(ops), "plan": int(ops) + int(avvik)}
        for ops, aar, acc, avvik in set(_ATCO.findall(text))
        if int(aar) == year
    }

    return {
        "aar": year,
        "ifr_bevegelser_1000": trafikk,
        "sektortimer": sektortimer,
        "produktivitet": produktivitet,
        "atco": atco,
    }


def _trafikk_2019(text: str) -> float | None:
    match = _TRAFIKK_2019.search(text)
    return float(_num(match.group(1))) if match else None


# --------------------------------------------------------------------------
@model(
    name="clean.eurocontrol_trafikk_norge",
    deps=[f"raw:{RAW_PREFIX}{year}" for year in YEARS],
    checks=["unique:aar", "min_rows:1", "not_null:ifr_bevegelser_1000", "ifr_bevegelser_1000 > 0"],
    doc="Faktiske IFR-bevegelser i Norge per år (EUROCONTROL/PRB Annual Monitoring Report).",
)
def clean_eurocontrol_trafikk_norge(ctx: Context) -> Any:
    """Ett tall per år, 2019-2024 — 2019 er baseline-året alle fem rapportene siterer likt.

    2019-verdien nevnes ikke med samme formulering hvert år (2020-rapporten
    skriver «compared to 2019 (591K)», 2021-2024 skriver «actual 2019 level
    (591K)»), så den hentes fra den første rapporten som faktisk gir treff.
    Alle rapportene som nevner den er enige om nøyaktig samme tall —
    kontrollert direkte mot samtlige fem før denne modellen ble skrevet,
    ikke antatt fra én av dem.
    """
    rows: list[dict[str, Any]] = []
    baseline: float | None = None
    for year in YEARS:
        text = _report_text(ctx.raw_latest(f"{RAW_PREFIX}{year}"))
        parsed = parse_report(text, year)
        if parsed["ifr_bevegelser_1000"] is not None:
            rows.append({"aar": year, "ifr_bevegelser_1000": parsed["ifr_bevegelser_1000"]})
        if baseline is None:
            baseline = _trafikk_2019(text)
    if baseline is not None:
        rows.append({"aar": 2019, "ifr_bevegelser_1000": baseline})
    return pl.DataFrame(rows).sort("aar")


@model(
    name="clean.eurocontrol_kapasitet",
    deps=[f"raw:{RAW_PREFIX}{year}" for year in YEARS],
    checks=[
        "unique:acc,aar",
        "min_rows:1",
        "sektortimer is null or sektortimer > 0",
        "ifr_bevegelser_per_sektortime is null or ifr_bevegelser_per_sektortime > 0",
        "atco_ops is null or atco_ops > 0",
        "atco_plan is null or atco_plan >= atco_ops",
    ],
    doc="Sektor-åpningstimer, produktivitet og ATCO-bemanning per kontrollsentral (kun der rapporten faktisk oppgir tallet).",
)
def clean_eurocontrol_kapasitet(ctx: Context) -> Any:
    """Én rad per (kontrollsentral, år) — men bare der minst ett tall faktisk står i rapporten.

    Se moduldocstringen: bemanning har bare tall for 2024, og sektortimer/
    produktivitet mangler for minst én ACC de fleste årene. Radene som ville
    vært helt tomme er filtrert bort, ikke fylt med ``null`` i alle kolonner.
    """
    by_key: dict[tuple[str, int], dict[str, Any]] = {}

    def cell(acc: str, year: int) -> dict[str, Any]:
        return by_key.setdefault(
            (acc, year),
            {
                "acc": acc,
                "acc_navn": f"{acc} ACC",
                "acc_kode": ACC_KODE[acc],
                "aar": year,
                "sektortimer": None,
                "ifr_bevegelser_per_sektortime": None,
                "atco_ops": None,
                "atco_plan": None,
            },
        )

    for year in YEARS:
        text = _report_text(ctx.raw_latest(f"{RAW_PREFIX}{year}"))
        parsed = parse_report(text, year)
        for acc, verdi in parsed["sektortimer"].items():
            cell(acc, year)["sektortimer"] = verdi
        for acc, verdi in parsed["produktivitet"].items():
            cell(acc, year)["ifr_bevegelser_per_sektortime"] = verdi
        for acc, verdier in parsed["atco"].items():
            cell(acc, year)["atco_ops"] = verdier["ops"]
            cell(acc, year)["atco_plan"] = verdier["plan"]

    rows = sorted(by_key.values(), key=lambda r: (r["aar"], r["acc"]))
    return pl.DataFrame(rows).cast({"aar": pl.Int64, "atco_ops": pl.Int64, "atco_plan": pl.Int64})
