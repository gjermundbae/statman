"""clean-laget for Vannmiljø-registreringene i Farrisvannet.

Rålaget er en HTML-tabell forkledd som ``.xls`` (se
``statman/sources/vannmiljo.py``), én fil per vannlokalitet. Denne modellen
parser HTML-en for hånd — DuckDB leser ikke HTML, og et bibliotek som
``pandas.read_html`` er ikke en avhengighet prosjektet ellers har — og
slår sammen de tre lokalitetene til én lang tabell, én rad per registrering.

Søket «Farris» på vannmiljøs faktaark ga 16 vannlokaliteter. De fleste er
enten fisk/sediment-engangsprøver, tilløpsbekker, eller et kortvarig
veiprosjekt-tilsyn 2019-2021 (siltgardin, «øst», «vest», «Gopledal») — se
den opprinnelige mulighetsvurderingen for hvorfor de ble vurdert og lagt
til side. De tre brukt her — Bakkepollen, Eikenesfjorden, Nesfjorden — er
de eneste med ``Aktivitetsnavn = "Overvåking av drikkevann"`` og Vestfold
Vann IKS som oppdragsgiver: det faktiske, flerårige overvåkingsprogrammet
for drikkevannskilden, ikke en enkeltstående undersøkelse.
"""

from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final

from statman.registry import Context, model

RAW_REFS: Final[dict[str, str]] = {
    "farris_bakkepollen": "vannmiljo/farris_bakkepollen",
    "farris_eikenesfjorden": "vannmiljo/farris_eikenesfjorden",
    "farris_nesfjorden": "vannmiljo/farris_nesfjorden",
}

# Kolonnenavn i kildetabellen -> feltnavn i clean-laget.
_COLUMNS: Final[dict[str, str]] = {
    "Vannlokalitetskode": "vannlokalitetskode",
    "Vannlokalitetsnavn": "vannlokalitet_navn",
    "Aktivitetsnavn": "aktivitetsnavn",
    "Oppdragsgiver": "oppdragsgiver",
    "Oppdragstaker": "oppdragstaker",
    "ParameterID": "parameter_id",
    "Parameternavn": "parameternavn",
    "Mediumnavn": "medium",
    "Prøvetakingstidspunkt": "provetakingstidspunkt_raw",
    "Operator": "operator",
    "Registreringsverdi": "verdi_raw",
    "Enhetsnavn": "enhet",
    "Øvre dyp": "ovre_dyp_raw",
    "Nedre dyp": "nedre_dyp_raw",
}


class _TableParser(HTMLParser):
    """Den enkleste HTML-tabellen som finnes: ingen nøstede tabeller, ingen rowspan."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(self._cell.strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell += data


def _parse_html_table(path: Path) -> list[dict[str, str]]:
    parser = _TableParser()
    parser.feed(path.read_text(encoding="utf-8"))
    if not parser.rows:
        return []
    header, *data = parser.rows
    return [dict(zip(header, row)) for row in data if len(row) == len(header)]


def _to_date(raw: str) -> dt.date | None:
    """«10/18/2011 12:00:00 AM» -> 2011-10-18. Klokkeslettet er alltid 00:00, aldri reell tid."""
    try:
        return dt.datetime.strptime(raw.strip(), "%m/%d/%Y %I:%M:%S %p").date()
    except ValueError:
        return None


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except ValueError:
        return None


@model(
    name="clean.vannmiljo_farris",
    deps=[f"raw:{ref}" for ref in RAW_REFS.values()],
    checks=[
        "not_null:vannlokalitet_id",
        "not_null:parameternavn",
        "not_null:provetakingstidspunkt",
        "not_null:verdi",
        "verdi >= 0",
    ],
    doc="Alle Vannmiljø-registreringer for Farrisvannets drikkevannsovervåking, én rad per prøve×dyp×parameter.",
)
def clean_vannmiljo_farris(ctx: Context) -> Any:
    import polars as pl

    records: list[dict[str, object]] = []
    for dataset, ref in RAW_REFS.items():
        path = ctx.raw_latest(ref)
        for raw_row in _parse_html_table(path):
            row = {_COLUMNS[k]: v for k, v in raw_row.items() if k in _COLUMNS}
            kode = row.get("vannlokalitetskode", "")
            _, _, id_del = kode.partition("-")
            records.append(
                {
                    "dataset": dataset,
                    "vannlokalitet_id": int(id_del) if id_del.isdigit() else None,
                    "vannlokalitet_navn": row.get("vannlokalitet_navn"),
                    "aktivitetsnavn": row.get("aktivitetsnavn") or None,
                    "oppdragsgiver": row.get("oppdragsgiver") or None,
                    "oppdragstaker": row.get("oppdragstaker") or None,
                    "parameter_id": row.get("parameter_id"),
                    "parameternavn": row.get("parameternavn"),
                    "medium": row.get("medium"),
                    "provetakingstidspunkt": _to_date(row.get("provetakingstidspunkt_raw", "")),
                    "operator": row.get("operator") or "=",
                    "verdi": _to_float(row.get("verdi_raw", "")),
                    "enhet": row.get("enhet") or None,
                    "ovre_dyp": _to_float(row.get("ovre_dyp_raw", "")),
                    "nedre_dyp": _to_float(row.get("nedre_dyp_raw", "")),
                }
            )

    return pl.DataFrame(
        records,
        schema={
            "dataset": pl.Utf8,
            "vannlokalitet_id": pl.Int64,
            "vannlokalitet_navn": pl.Utf8,
            "aktivitetsnavn": pl.Utf8,
            "oppdragsgiver": pl.Utf8,
            "oppdragstaker": pl.Utf8,
            "parameter_id": pl.Utf8,
            "parameternavn": pl.Utf8,
            "medium": pl.Utf8,
            "provetakingstidspunkt": pl.Date,
            "operator": pl.Utf8,
            "verdi": pl.Float64,
            "enhet": pl.Utf8,
            "ovre_dyp": pl.Float64,
            "nedre_dyp": pl.Float64,
        },
    )
