"""SSB KLASS — klassifikasjonene bak kodene i Statistikkbanken.

Statistikkbanken leverer koder og etiketter i samme svar, så de fleste
analyser trenger ikke denne kilden. Yrkesanalysen gjør det likevel, av én
grunn: tabell 11658 har ikke et fullstendig hovedgruppenivå. Den slår
sammen militære yrker og høyskoleyrker til én kode ``3_01-03``
(«Høyskole- og militære yrker»), og lar dermed to av STYRK-08s ti
hovedgrupper være uten navn. Skal 407 yrker grupperes i de ti gruppene
standarden faktisk har, må navnene komme fra standarden.

KLASS er den kilden. Standard for yrkesklassifisering er klassifikasjon 7,
og ``codesAt`` gir hele hierarkiet på én dato: kode, forelderkode, nivå og
navn, for alle fire nivåer på én gang. Vi henter det uendret.

Ingen dokumentert kallgrense. Vi bruker samme throttle som Statistikkbanken
framfor å la være — det er ett kall i året, og marginen koster ingenting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from statman import io
from statman.http import RateLimiter, get

SOURCE: Final[str] = "klass"
BASE: Final[str] = "https://data.ssb.no/api/klass/v1"
LICENSE: Final[str] = "NLOD / CC BY 4.0 — krever kildehenvisning til SSB"

# Klassifikasjonsnummeret er ikke gjettbart, så det står navngitt her.
STYRK08: Final[int] = 7

LIMITER: Final[RateLimiter] = RateLimiter(max_calls=25, per_seconds=10.0)


def codes_url(classification: int, base: str | None = None) -> str:
    return f"{(base or BASE).rstrip('/')}/classifications/{classification}/codesAt"


def fetch_codes(
    classification: int = STYRK08,
    *,
    date: str,
    dataset: str | None = None,
    lang: str = "nb",
    timeout: float = 60.0,
) -> Path:
    """Hent et helt kodeverk slik det så ut på ``date``, og skriv det uendret.

    ``date`` er obligatorisk og på formen ``YYYY-MM-DD``. KLASS har ingen
    «nyeste»-variant av dette endepunktet, og en dato som settes av seg selv
    ved kjøretid ville gjort to hentinger uforlignbare uten at noe i
    kvitteringen sa fra. Datoen er et valg, og tas av den som henter.
    """
    url = codes_url(classification)
    params = {"date": date, "language": lang}
    response = get(url, params=params, limiter=LIMITER, timeout=timeout)
    return io.write_raw(
        SOURCE,
        dataset or f"{classification}_codes",
        response.content,
        {
            "endpoint": url,
            "classification": classification,
            "params": params,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "license": LICENSE,
            "kind": "classification",
        },
        suffix="json",
    )
