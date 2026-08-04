"""Norges Bank — styringsrenten via data.norges-bank.no (SDMX REST).

Ny kilde, samme regel som alle de andre: hent og skriv ned uendret, tolk
ingenting her.

Grensesnittet er `https://data.norges-bank.no/api/data/<dataflow>/<nøkkel>`,
der `IR` er rentedataflyten og `B.KPRA.SD` er nøkkelen for styringsrenten
(«B» = virkedagsfrekvens, «KPRA» = Key Policy Rate, «SD» = styringsrenten
selv, ikke foliorenten eller D-lånsrenten). Ingen autentisering trengs.

Formatet er satt til ``csv``, ikke SDMX-JSON. API-et støtter begge, men
CSV-en er allerede en flat tabell med ``TIME_PERIOD``/``OBS_VALUE`` — samme
grunn som pollofpolls.no-konnektoren valgte CSV over sitt opprinnelige
format. ``locale=en`` er satt med vilje: med ``locale=no`` bruker
``OBS_VALUE`` norsk desimalkomma («8,5»), som gjør kolonnen til tekst i
stedet for tall før den er dekodet et sted til.

Serien er virkedager («Business»), ikke kalenderdager — renten er den samme
tallet hver dag mellom rentemøtene, notert ved dagens slutt. Det er ikke et
valg konnektoren tar, det er slik kilden selv publiserer den.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from statman import io
from statman.http import get

SOURCE: Final[str] = "norges_bank"
DATASET: Final[str] = "styringsrente"
BASE: Final[str] = "https://data.norges-bank.no/api/data"
DATAFLOW: Final[str] = "IR"
SERIES_KEY: Final[str] = "B.KPRA.SD"
LICENSE: Final[str] = "Norges Bank — åpne data, gjenbruk med kildehenvisning"


def fetch_key_policy_rate(
    *,
    start: str = "1991-01-01",
    end: str | None = None,
    timeout: float = 60.0,
) -> Path:
    """Hent hele styringsrenteserien (virkedagsnoteringer) som CSV.

    ``start`` er satt tidligere enn styringsrenten fantes som eget
    virkemiddel (innført 1991); APIet klipper selv til der serien faktisk
    begynner, akkurat som pollofpolls-konnektoren gjør med sin ``start``.
    """
    url = f"{BASE}/{DATAFLOW}/{SERIES_KEY}"
    params = {"format": "csv", "locale": "en", "startPeriod": start}
    if end:
        params["endPeriod"] = end
    response = get(url, params=params, timeout=timeout)
    return io.write_raw(
        SOURCE,
        DATASET,
        response.content,
        {
            "endpoint": url,
            "dataflow": DATAFLOW,
            "series_key": SERIES_KEY,
            "params": params,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "license": LICENSE,
            "kind": "data",
        },
        suffix="csv",
    )
