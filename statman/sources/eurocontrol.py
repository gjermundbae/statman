"""EUROCONTROL / Performance Review Body — "PRB Annual Monitoring Report", Norge.

Ikke SSB og ikke et API: PRB (Performance Review Body, oppnevnt av EU-
kommisjonen under Single European Sky) publiserer én PDF-rapport per land
per år, med kapasitets-, miljø- og kostnadstall for landets ANSP (for Norge:
Avinor Flysikring AS). Nedlastingssida er
``https://www.sesperformance.eu/download``, og hver landrapport ligger på
``.../download/<år>/PRB-Annual-Monitoring-Report_<Land>_<år>.pdf``.

Rapportene er ikke datatabeller — de er løpende tekst med tall vevet inn i
punkter («Bodo ACC registered 7.62 IFR movements per one sector opening
hour in 2024»). ``clean.eurocontrol_trafikk_norge`` og
``clean.eurocontrol_kapasitet`` trekker ut nøyaktig de tallene som faktisk
står skrevet, år for år — se docstringen der for hvorfor bare noen av de tre
kontrollsentralene har tall i enkelte år.

Rådataene her er PDF-bytes, ikke JSON eller CSV som resten av kildene —
``io.write_raw`` bryr seg ikke om formatet, bare at det skrives uendret.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from statman import io
from statman.http import get

SOURCE: Final[str] = "eurocontrol"
BASE: Final[str] = "https://www.sesperformance.eu/download"
LAND: Final[str] = "Norway"
LICENSE: Final[str] = (
    "EUROCONTROL Performance Review Body — PRB Annual Monitoring Report. "
    "Offentlig tilgjengelig, ingen innlogging."
)


def dataset(year: int) -> str:
    return f"prb_norway_{year}"


def fetch_prb_norway(year: int, *, timeout: float = 60.0) -> Path:
    """Hent PRB-årsrapporten for Norge for ``year`` som PDF, uendret.

    URL-mønsteret er observert direkte fra nedlastingssidas HTML
    (``href="download/<år>/PRB-Annual-Monitoring-Report_Norway_<år>.pdf"``),
    ikke gjettet — sida i seg selv er en ren filliste uten API.
    """
    url = f"{BASE}/{year}/PRB-Annual-Monitoring-Report_{LAND}_{year}.pdf"
    response = get(url, timeout=timeout)
    return io.write_raw(
        SOURCE,
        dataset(year),
        response.content,
        {
            "endpoint": url,
            "year": year,
            "land": LAND,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "license": LICENSE,
            "kind": "data",
        },
        suffix="pdf",
    )
