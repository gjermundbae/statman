"""Utflytterrosteret — hvem, hvilket land, når, og hvor det er dokumentert.

Ikke en API-kilde: dette er en håndkuratert liste over norske
skatteutflyttere, verifisert mot navngitte artikler i norsk presse (NRK,
Wikipedia/SNL, DN-avledede oppslag). Samme prinsipp som
``statman/sources/synthetic.py`` — også data som ikke kommer fra et API
skrives uendret til rålaget, med kilde i kvitteringen, i stedet for å gå
rett i en modell. Det gjør at roasteret kan endres (ny person, rettet år)
uten at noen må huske å oppdatere to steder.

Utvalgskriterium: personen må være offentlig kjent for nettopp denne
utflyttingen, med minst én navngitt kilde som ikke er omstridt. Ett land per
person i dette datasettet — poenget er én representant per land i tabellen,
ikke en fullstendig liste over norske skatteutflyttere.

Landkodene er FIFA sine lagkoder (``SUI`` for Sveits, ikke ISO ``CHE``), for
å matche rett inn mot ``clean.fifa_ranking`` uten en oversettelsestabell.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from statman import io

SOURCE: Final[str] = "utflyttere"
DATASET: Final[str] = "roster"

ROSTER: Final[tuple[dict[str, object], ...]] = (
    {
        "navn": "Kjell Inge Røkke",
        "fifa_kode": "SUI",
        "land_navn": "Sveits",
        "sted": "Lugano",
        "flyttet_aar": 2022,
        "notat": "Meldte flytting til Lugano i Sveits i 2022, med 17,8 milliarder kroner i skattbar formue.",
        "kilde_navn": "NRK",
        "kilde_url": "https://www.nrk.no/norge/kjell-inge-rokke-melder-flytting-til-sveits-1.16100704",
    },
    {
        "navn": "John Fredriksen",
        "fifa_kode": "CYP",
        "land_navn": "Kypros",
        "sted": "Limassol",
        "flyttet_aar": 2006,
        "notat": "Utvandret fra Norge i 1978 og har ikke betalt skatt hit siden. Ble kypriotisk statsborger i 2006.",
        "kilde_navn": "Store norske leksikon",
        "kilde_url": "https://snl.no/John_Fredriksen",
    },
    {
        "navn": "Kristian Siem",
        "fifa_kode": "ENG",
        "land_navn": "England",
        "sted": "London",
        "flyttet_aar": 1999,
        "notat": "Styreleder i Subsea 7 og Siem Industries, bosatt i London i over 25 år.",
        "kilde_navn": "Wikipedia (engelsk)",
        "kilde_url": "https://en.wikipedia.org/wiki/Kristian_Siem",
    },
    {
        "navn": "Ole Andreas Halvorsen",
        "fifa_kode": "USA",
        "land_navn": "USA",
        "sted": "Greenwich/Darien, Connecticut",
        "flyttet_aar": 1990,
        "notat": "Grunnlegger og sjef for hedgefondet Viking Global Investors, bosatt i Connecticut.",
        "kilde_navn": "Wikipedia (engelsk)",
        "kilde_url": "https://en.wikipedia.org/wiki/Ole_Andreas_Halvorsen",
    },
    {
        "navn": "Isabel Raad",
        "fifa_kode": "UAE",
        "land_navn": "De forente arabiske emirater",
        "sted": "Dubai",
        "flyttet_aar": 2023,
        "notat": "Influenser og gründer (Ivorie Studio, Nude Beauty), bosatt i Dubai siden 2023. Har kjøpt luksusvilla der for 43 millioner kroner.",
        "kilde_navn": "TV2",
        "kilde_url": "https://www.tv2.no/underholdning/skatteregningen-barbert-etter-dubai-flytting/18340146/",
    },
)


def ingest() -> Path:
    """Skriv roasteret til rålaget, som om det kom fra en kilde med et API."""
    payload = json.dumps(list(ROSTER), ensure_ascii=False, indent=None).encode("utf-8")
    return io.write_raw(
        SOURCE,
        DATASET,
        payload,
        {
            "endpoint": "manual://redaksjonelt-kuratert",
            "license": "Redaksjonelt sammenstilt fra navngitte pressekilder — se kilde_url per rad",
            "kind": "data",
            "rows": len(ROSTER),
            "utvalgskriterium": (
                "Offentlig kjent, navngitt kilde per person, ett land per person, "
                "ingen omstridte eller dårlig dokumenterte tilfeller."
            ),
        },
    )
