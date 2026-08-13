"""clean-laget for STYRK-08 — Standard for yrkesklassifisering.

Mekanisk lag: KLASS-svaret er allerede én rad per kode. Det eneste som skjer
her er utpakking av lista, typing av nivået, og at forelderkoden på nivå 1
gjøres eksplisitt null i stedet for å komme som strengen ``"null"``.

Hierarkiet er strengt: hver kode på nivå *n* har en forelder på nivå *n-1*,
og de fire nivåene er hovedgruppe (10), yrkesgruppe (43), yrkesundergruppe
(122) og yrke (407). Sjekkene under holder på nettopp det — en standard som
plutselig ikke er et tre, er ikke noe å gruppere en figur etter.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

RAW_STYRK: Final[str] = "klass/styrk08_codes"

# Hva nivåene heter. Brukes til etiketter, og som en påminnelse om at «yrke»
# er det fireside nivået — de tre andre er grupper av yrker, ikke yrker.
NIVAA: Final[dict[int, str]] = {
    1: "hovedgruppe",
    2: "yrkesgruppe",
    3: "yrkesundergruppe",
    4: "yrke",
}


@model(
    name="clean.styrk",
    deps=[f"raw:{RAW_STYRK}"],
    checks=[
        "unique:kode",
        "not_null:navn",
        "nivaa between 1 and 4",
        # Kodelengden *er* nivået i STYRK-08. Er den ikke det, har vi enten
        # fått et annet kodeverk eller en kode vi ikke forstår.
        "length(kode) = nivaa",
    ],
    doc="STYRK-08 (KLASS 7), alle fire nivåer med forelderkode.",
)
def clean_styrk(ctx: Context) -> Any:
    path = ctx.raw_latest(RAW_STYRK)
    return ctx.sql(f"""
        with utpakket as (
            select unnest(codes) as kode
            from read_json('{path.as_posix()}')
        )
        select
            kode.code                    as kode,
            nullif(kode.parentCode, '')  as forelder,
            cast(kode.level as integer)  as nivaa,
            kode.name                    as navn
        from utpakket
        order by kode
    """)
