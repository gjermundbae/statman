"""clean-laget for Norges Banks styringsrente.

Mekanisk lag: rålaget er allerede en flat CSV (se
``statman/sources/norges_bank.py`` for hvorfor), så det eneste som skjer her
er typing og et kolonnenavnbytte til prosjektets stil. Ingen rader filtreres
bort og ingen hull fylles inn.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

RAW_STYRINGSRENTE: Final[str] = "norges_bank/styringsrente"


@model(
    name="clean.styringsrente",
    deps=[f"raw:{RAW_STYRINGSRENTE}"],
    checks=[
        "unique:dato",
        "not_null:dato",
        "not_null:rente_pst",
    ],
    doc="Styringsrenten (Norges Bank, IR/B.KPRA.SD). Én rad per virkedag renten ble notert, fra 1991.",
)
def clean_styringsrente(ctx: Context) -> Any:
    path = ctx.raw_latest(RAW_STYRINGSRENTE)
    return ctx.sql(f"""
        select
            cast(TIME_PERIOD as date) as dato,
            cast(OBS_VALUE as double)  as rente_pst
        from read_csv('{path.as_posix()}', delim=';', header=true, all_varchar=true)
        order by dato
    """)
