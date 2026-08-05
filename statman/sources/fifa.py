"""FIFA/Coca-Cola Men's World Ranking — inside.fifa.com.

Offisiell kilde, men ingen offentlig JSON-API: siden er en Next.js-app der
selve rangeringstabellen aldri ligger i den server-rendrede HTML-en (verken
i ``__NEXT_DATA__`` eller i ``/_next/data/.../men.json`` — begge inneholder
bare datovelgeren og konfødersjonslisten). Tabellen bygges klient-side, og
begge XHR-kallene siden faktisk gjør
(``/api/live-world-ranking/get-international-ranking-window`` og
``/api/live-world-ranking/get-match-window-matches``) sitter bak Akamai Bot
Manager, som avviser ren ``httpx``-trafikk uten en løst JS-utfordring —
bekreftet ved at nøyaktig samme spørring gir 400 med tomt svar fra
kommandolinjen. Samme situasjon som Vannmiljøs WAF i
``statman/sources/vannmiljo.py``, bare uten en User-Agent som løser det.

``fetch()`` leser derfor ikke fra nettet, men fra en lokal kvittering
(``_fixtures/fifa_world_ranking_men_20260805.json``) hentet ut 2026-08-05 ved
å lese DOM-en på https://inside.fifa.com/fifa-rankings/world-ranking/men i en
faktisk nettleserøkt — «Show full rankings» utvidet tabellen fra topp 10 til
alle 211 lag, og hver rad ble lest ut av ``.custom-rank-cell_rankNumber``,
``.custom-team-cell_teamName`` og ``.custom-points-cell_points``. Det er
samme prinsipp som Vannmiljø-modulens kommentar: dette er ikke en maskerade,
det er den eneste måten å få tallene FIFA selv publiserer på akkurat denne
siden. Innholdet skrives uendret til rålaget, med kilde og hentemetode i
kvitteringen, akkurat som enhver annen henting.

Siden viste selv at dette var siste offisielle oppdatering: «Last official
update: 20 July 2026», med neste ventet 7. oktober 2026 — bekreftet av
``lastUpdateDate``/``nextUpdateDate`` i sidens egne data. Rangeringen er
altså ikke fersk hver dag; den ligger fast mellom disse to datoene.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from statman import io

SOURCE: Final[str] = "fifa"
DATASET: Final[str] = "world_ranking_men"
ENDPOINT: Final[str] = "https://inside.fifa.com/fifa-rankings/world-ranking/men"
LICENSE: Final[str] = "FIFA/Coca-Cola Men's World Ranking — offentlig, ikke-nedlastbar tabell"

_FIXTURES: Final[Path] = Path(__file__).parent / "_fixtures"
_CAPTURE_FILE: Final[str] = "fifa_world_ranking_men_20260805.json"
_CAPTURED_AT: Final[str] = "2026-08-05T00:00:00Z"
_RANKING_EFFECTIVE_DATE: Final[str] = "2026-07-20"
_NEXT_UPDATE: Final[str] = "2026-10-07"


def fetch(*, capture_file: str = _CAPTURE_FILE) -> Path:
    """Skriv den fastfrosne rangeringskvitteringen til rålaget, uendret.

    Ingen nettverkskall — se moduldocstringen for hvorfor. ``capture_file``
    peker på en fil under ``_fixtures/``; parameteren finnes bare så en
    framtidig ny uttrekking (ny dato, ny fil) kan brukes uten å endre koden.
    """
    path = _FIXTURES / capture_file
    payload = path.read_bytes()
    return io.write_raw(
        SOURCE,
        DATASET,
        payload,
        {
            "endpoint": ENDPOINT,
            "http_status": None,
            "final_url": ENDPOINT,
            "license": LICENSE,
            "kind": "data",
            "capture_method": (
                "Manuelt lest ut av DOM-en i en faktisk nettleserøkt (Akamai Bot "
                "Manager blokkerer rene HTTP-kall til de underliggende XHR-endepunktene). "
                "Se moduldocstring i statman/sources/fifa.py."
            ),
            "captured_at": _CAPTURED_AT,
            "ranking_effective_date": _RANKING_EFFECTIVE_DATE,
            "next_official_update": _NEXT_UPDATE,
        },
        suffix="json",
    )
