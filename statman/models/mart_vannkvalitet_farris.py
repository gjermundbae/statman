"""mart-laget for drikkevannsovervåkingen i Farrisvannet.

To tabeller, to spørsmål — begge rene tidsutviklinger, ingen sammenhenger
mellom dem.

**mart.farris_vannkvalitet_dato** er råvannet slik Vestfold Vann IKS selv
måler det ved Bakkepollen: 78 prøvedatoer, april-november, 2011-2021. Hver
dato er et fullt dypprofil (1, 10, 20, 30, 40, 50, 60 meter) for alle
parametere — bekreftet i clean-laget, ikke antatt. Denne tabellen bruker
bare **1 meter** (øverste sjikt), fordi det er der algevekst og
fargeendring faktisk skjer, og fordi det gjør «utvikling over tid» til ett
tall per dato i stedet for et dypsnitt som skjuler akkurat det poenget.
Dypere sjikt ligger urørt i ``clean.vannmiljo_farris`` for den som vil se
resten av profilen.

**mart.farris_algeblomst_aar** er de årlige cyanobakterie-toppmålingene
(«Cyano maks») og eutrofieringsindeksen (nEQR) ved to andre punkter i
innsjøen, Eikenesfjorden og Nesfjorden — 2010/2012-2025. Én måling i året,
ikke et gjennomsnitt vi har regnet ut selv.
"""

from __future__ import annotations

from typing import Any

from statman.registry import Context, model

_BAKKEPOLLEN_PARAMS: dict[str, str] = {
    "FARGE": "fargetall_mg_pt_l",
    "TURB": "turbiditet_fnu",
    "P-TOT": "totalfosfor_ug_l",
    "P-ORTO": "ortofosfat_ug_l",
    "N-TOT": "totalnitrogen_ug_l",
    "PH": "ph",
    "FE": "jern_ug_l",
    "MN": "mangan_ug_l",
    "E-KOLI": "e_coli_per_100ml",
    "KOLI": "koliforme_bakterier_per_100ml",
    "INTEST": "intestinale_enterokokker_per_100ml",
    "KIMTALL": "kimtall_22c_per_100ml",
    "CLOPER": "clostridium_perfringens_per_100ml",
}


@model(
    name="mart.farris_vannkvalitet_dato",
    deps=["clean.vannmiljo_farris"],
    checks=[
        "unique:dato",
        "not_null:dato",
    ],
    doc="Råvannskvalitet ved Bakkepollen, øverste meter, én rad per prøvedato 2011-2021.",
)
def farris_vannkvalitet_dato(ctx: Context) -> Any:
    pivot_cols = ",\n            ".join(
        f"max(case when parameter_id = '{pid}' then verdi end) as {navn}"
        for pid, navn in _BAKKEPOLLEN_PARAMS.items()
    )
    return ctx.sql(f"""
        select
            provetakingstidspunkt as dato,
            extract(year from provetakingstidspunkt)::integer  as aar,
            extract(month from provetakingstidspunkt)::integer as maaned,
            {pivot_cols}
        from clean_vannmiljo_farris
        where dataset = 'farris_bakkepollen'
          and ovre_dyp = 1
        group by all
        order by dato
    """)


@model(
    name="mart.farris_algeblomst_aar",
    deps=["clean.vannmiljo_farris"],
    checks=[
        "unique:aar,lokalitet",
        "not_null:aar",
        "not_null:lokalitet",
    ],
    doc="Årlig cyanobakterie-maks og eutrofieringsindeks, Eikenesfjorden og Nesfjorden i Farris, 2010-2025.",
)
def farris_algeblomst_aar(ctx: Context) -> Any:
    return ctx.sql("""
        select
            extract(year from provetakingstidspunkt)::integer as aar,
            vannlokalitet_navn                                 as lokalitet,
            max(case when parameter_id = 'CYANOM'    then verdi end) as cyano_maks_mg_l,
            max(case when parameter_id = 'PPNEQR_E'  then verdi end) as planteplankton_neqr
        from clean_vannmiljo_farris
        where dataset in ('farris_eikenesfjorden', 'farris_nesfjorden')
        group by all
        order by aar, lokalitet
    """)
