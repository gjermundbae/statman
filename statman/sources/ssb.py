"""SSB Statistikkbanken via PxWebApi 2.0.

Grenser (per SSBs dokumentasjon): maks 30 kall per 10 sekunder og 150 000
celler per kall. Vi ligger med vilje litt under kallgrensa.

Basis-URL kan overstyres med ``STATMAN_SSB_BASE``. Standard er å prøve
``/v2`` først og falle tilbake til ``/v2-beta``, siden SSB har flyttet på
denne stien underveis i overgangen fra PxWeb 1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

from statman import io
from statman.http import RateLimiter, get

SOURCE: Final[str] = "ssb"
BASE_ENV: Final[str] = "STATMAN_SSB_BASE"
BASE_CANDIDATES: Final[tuple[str, ...]] = (
    "https://data.ssb.no/api/pxwebapi/v2",
    "https://data.ssb.no/api/pxwebapi/v2-beta",
)
LICENSE: Final[str] = "NLOD / CC BY 4.0 — krever kildehenvisning til SSB"

# SSB tillater 30 kall per 10 sekunder. Vi bruker 25 for margin.
LIMITER: Final[RateLimiter] = RateLimiter(max_calls=25, per_seconds=10.0)

_resolved_base: str | None = None


# --------------------------------------------------------------------------
# Rene hjelpefunksjoner (testbare uten nett)
# --------------------------------------------------------------------------
def data_params(
    value_codes: Mapping[str, str | Iterable[str]] | None = None,
    *,
    codelists: Mapping[str, str] | None = None,
    lang: str = "no",
    fmt: str = "json-stat2",
) -> dict[str, str]:
    """Bygg spørrestrengen for et data-kall.

    PxWebApi 2.0 tar filtre som ``valueCodes[VARIABEL]=KODE``. Verdien kan
    være en enkeltkode, en liste, eller et uttrykk som ``TOP(12)`` og ``*``.

    ``codelists`` velger en alternativ kodeliste for en variabel, som
    ``codelist[Region]=agg_KommSummerHist``. Det er slik man ber SSB om en
    tidsserie i én bestemt kommuneinndeling i stedet for kodene som gjaldt
    det enkelte året — se ``statman ssb-codelists``.
    """
    params: dict[str, str] = {"lang": lang, "format": fmt}
    for variable, codelist in (codelists or {}).items():
        params[f"codelist[{variable}]"] = codelist
    for variable, codes in (value_codes or {}).items():
        value = codes if isinstance(codes, str) else ",".join(str(c) for c in codes)
        params[f"valueCodes[{variable}]"] = value
    return params


def data_url(table_id: str, base: str | None = None) -> str:
    return f"{(base or base_url()).rstrip('/')}/tables/{table_id}/data"


def metadata_url(table_id: str, base: str | None = None) -> str:
    return f"{(base or base_url()).rstrip('/')}/tables/{table_id}/metadata"


def count_cells(payload: bytes) -> int:
    """Antall celler i et json-stat2-svar. Brukes til å se om vi nærmer oss grensa."""
    try:
        doc: dict[str, Any] = json.loads(payload)
    except (ValueError, TypeError):
        return -1
    size = doc.get("size")
    if not isinstance(size, list) or not size:
        return -1
    cells = 1
    for dim in size:
        cells *= int(dim)
    return cells


# --------------------------------------------------------------------------
# Basis-URL
# --------------------------------------------------------------------------
def base_url() -> str:
    """Gjeldende basis-URL. Bruker env-overstyring, ellers sist verifiserte, ellers første kandidat."""
    override = os.environ.get(BASE_ENV)
    if override:
        return override.rstrip("/")
    return _resolved_base or BASE_CANDIDATES[0]


def probe(*, timeout: float = 15.0) -> dict[str, Any]:
    """Sjekk hvilke basis-URL-er som svarer, og husk den som virker.

    Returnerer ``{"working": <url|None>, "tried": {url: status|feil}}``.
    Kjør denne først når noe ser rart ut — den skiller nettverksfeil fra
    at SSB har flyttet endepunktet.
    """
    global _resolved_base
    override = os.environ.get(BASE_ENV)
    candidates = (override.rstrip("/"),) if override else BASE_CANDIDATES
    tried: dict[str, Any] = {}
    working: str | None = None
    for candidate in candidates:
        url = f"{candidate}/tables"
        try:
            response = get(
                url,
                params={"lang": "no", "pageSize": "1"},
                limiter=LIMITER,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - vi vil vise feilen, ikke svelge den
            tried[candidate] = f"{type(exc).__name__}: {exc}"
            continue
        tried[candidate] = response.status_code
        if working is None:
            working = candidate
    if working:
        _resolved_base = working
    return {"working": working, "tried": tried}


# --------------------------------------------------------------------------
# Henting
# --------------------------------------------------------------------------
def fetch_table(
    table_id: str,
    *,
    value_codes: Mapping[str, str | Iterable[str]] | None = None,
    codelists: Mapping[str, str] | None = None,
    dataset: str | None = None,
    lang: str = "no",
    fmt: str = "json-stat2",
    timeout: float = 60.0,
) -> Path:
    """Hent en tabell og skriv svaret uendret til rålaget. Returnerer versjonsmappa.

    ``dataset`` overstyrer mappenavnet under ``raw/ssb/``. Bruk det når du
    henter samme tabell med to ulike utsnitt — kommuner og fylker fra 06913
    er to datasett, ikke to versjoner av det samme.
    """
    params = data_params(value_codes, codelists=codelists, lang=lang, fmt=fmt)
    url = data_url(table_id)
    response = get(url, params=params, limiter=LIMITER, timeout=timeout)
    payload = response.content
    return io.write_raw(
        SOURCE,
        dataset or table_id,
        payload,
        {
            "endpoint": url,
            "table_id": table_id,
            "params": params,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "cells": count_cells(payload),
            "license": LICENSE,
            "kind": "data",
        },
    )


def fetch_codelist(codelist_id: str, *, lang: str = "no", timeout: float = 60.0) -> dict[str, Any]:
    """Slå opp en kodeliste. Brukes til å se hva en aggregering faktisk gjør.

    Hentes ikke til rålaget — dette er oppslag mens du utforsker, ikke data
    en modell er avhengig av.
    """
    url = f"{base_url()}/codeLists/{codelist_id}"
    response = get(url, params={"lang": lang}, limiter=LIMITER, timeout=timeout)
    return dict(response.json())


def fetch_metadata(table_id: str, *, lang: str = "no", timeout: float = 60.0) -> Path:
    """Hent metadata for en tabell — variabler og gyldige koder."""
    url = metadata_url(table_id)
    params = {"lang": lang}
    response = get(url, params=params, limiter=LIMITER, timeout=timeout)
    return io.write_raw(
        SOURCE,
        f"{table_id}__metadata",
        response.content,
        {
            "endpoint": url,
            "params": params,
            "http_status": response.status_code,
            "final_url": str(response.url),
            "license": LICENSE,
            "kind": "metadata",
        },
    )
