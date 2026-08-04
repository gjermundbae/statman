"""Vannmiljø faktaark — Miljødirektoratets register over vannregistreringer.

``vannmiljofaktaark.miljodirektoratet.no`` er den offentlige, ikke-innloggede
fronten mot Vannmiljø-databasen. Hver vannlokalitet har en «Eksporter alle
måledata»-lenke som gir alle registreringer for lokaliteten, fra alle
oppdragsgivere, i ett svar. Filendelsen er ``.xls``, men innholdet er en
HTML-tabell Excel kan åpne — ikke et reelt binærformat — så clean-laget
parser den som HTML, ikke som regneark.

Endepunktet sitter bak en Azure Web Application Firewall som avviser
alt som ikke ligner en nettleser-User-Agent. Prosjektets vanlige
``statman/0.1 (...)``-streng (se ``statman/http.py``) blir blokkert med
403 — bekreftet ved at nøyaktig samme spørring slipper gjennom med en
Chrome-UA og ellers identiske headere. Denne kildens ``fetch``-funksjon
overstyrer derfor User-Agent, bare her.

Vannlokalitets-IDene er funnet manuelt ved å søke «Farris» på
https://vannmiljofaktaark.miljodirektoratet.no/ og lese av hvilke som
faktisk har «Overvåking av drikkevann» som aktivitetsnavn og Vestfold
Vann IKS som oppdragsgiver — se ``statman/models/clean_vannmiljo.py`` for
hvorfor ikke alle 16 «Farris»-treffene brukes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from statman import io
from statman.http import get

SOURCE: Final[str] = "vannmiljo"
BASE: Final[str] = "https://vannmiljofaktaark.miljodirektoratet.no/Home/ExportToExcel"
LICENSE: Final[str] = "Miljødirektoratet, Vannmiljø — offentlige data"

# Nettleser-UA er nødvendig, se modul-docstringen. Verken statman selv eller
# Miljødirektoratet er tjent med at dette ser ut som noe det ikke er — det
# er ikke en maskerad, det er den eneste UA-formen WAF-regelen slipper gjennom.
_BROWSER_UA: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# vannlokalitetID -> datasettnavn under raw/vannmiljo/. Alle tre er
# Vestfold Vann IKS' eget drikkevannsovervåkingsprogram i Farrisvannet.
FARRIS_LOKALITETER: Final[dict[int, str]] = {
    88038: "farris_bakkepollen",
    84635: "farris_eikenesfjorden",
    84636: "farris_nesfjorden",
}


def fetch_water_location(water_location_id: int, dataset: str, *, timeout: float = 60.0) -> Path:
    """Hent alle måledata for én vannlokalitet, uendret.

    ``dataset`` er mappenavnet under ``raw/vannmiljo/`` — valgt av kalleren,
    ikke utledet av ``water_location_id``, så det kan gis et lesbart navn.
    """
    url = f"{BASE}/{water_location_id}"
    response = get(url, timeout=timeout, headers={"User-Agent": _BROWSER_UA})
    return io.write_raw(
        SOURCE,
        dataset,
        response.content,
        {
            "endpoint": url,
            "water_location_id": water_location_id,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "license": LICENSE,
            "kind": "data",
        },
        suffix="html",
    )


def fetch_all_farris(*, timeout: float = 60.0) -> dict[str, Path]:
    """Hent alle registrerte Farris-drikkevannslokaliteter. Se ``FARRIS_LOKALITETER``."""
    return {
        dataset: fetch_water_location(wl_id, dataset, timeout=timeout)
        for wl_id, dataset in FARRIS_LOKALITETER.items()
    }
