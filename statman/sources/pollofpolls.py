"""pollofpolls.no — redaksjonelt beregnet snitt av norske meningsmålinger.

Ikke offentlig statistikk og ikke SSB: et snitt tredjepartssiden selv
regner ut av de publiserte meningsmålingene, med en metode de dokumenterer
under ``?cmd=Om``, men som vi ikke kontrollerer eller kan etterprøve fra
utsiden. Brukes fordi det er den eneste kilden i prosjektet med oppslutning
mellom valgårene — se ``examples/preben_meningsmalinger.py`` for hvorfor
det trengs.

Sida har en «Last ned»-lenke som gir CSV direkte, dokumentert her:
https://www.pollofpolls.no/lastned.csv?tabell=gallupsnitttabell&antall=<n>
&type=riks&int=m&kommuneid=0&start=<åååå-mm-dd>&slutt=<åååå-mm-dd>

Fila er uansett hva ``Content-Type``-headeren sier faktisk Latin-1, ikke
UTF-8 — ``Høyre`` og ``Rødt`` kommer ut som ``H\\xf8yre`` og ``R\\xf8dt`` hvis
man tror på headeren. Rålaget skriver bytes uendret, som alltid; avkodingen
skjer i clean-modellen.

Månedlig er den fineste oppløsningen APIet tilbyr for et snitt over tid —
``int=y`` (årlig) finnes ikke, bare ``int=m``. Rålaget dekker fra januar
2008, uansett hvor langt tilbake ``start`` settes; det er der
tredjepartens egen serie begynner, ikke en grense vi har satt.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Final

from statman import io
from statman.http import get

SOURCE: Final[str] = "pollofpolls"
URL: Final[str] = "https://www.pollofpolls.no/lastned.csv"
LICENSE: Final[str] = (
    "pollofpolls.no — redaksjonelt beregnet snitt, ikke offisiell statistikk "
    "eller enkeltmålinger. Bruk med kildehenvisning."
)


def fetch_stortinget_snitt(
    *,
    start: str = "2000-01-01",
    slutt: str | None = None,
    timeout: float = 30.0,
) -> Path:
    """Hent det månedlige landsdekkende snittet for stortingsvalg.

    ``start`` er satt tidligere enn dataene faktisk går, med vilje — se
    modulens docstring. ``slutt`` er dagens dato hvis ikke oppgitt, så
    kjøringen alltid får med til og med forrige måned.
    """
    params = {
        "tabell": "gallupsnitttabell",
        "antall": "5000",
        "type": "riks",
        "int": "m",
        "kommuneid": "0",
        "start": start,
        "slutt": slutt or dt.date.today().isoformat(),
    }
    response = get(URL, params=params, timeout=timeout)
    return io.write_raw(
        SOURCE,
        "stortinget_snitt",
        response.content,
        {
            "endpoint": URL,
            "params": params,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "license": LICENSE,
            "kind": "data",
        },
        suffix="csv",
    )
