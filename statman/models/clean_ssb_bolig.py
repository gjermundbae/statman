"""clean-laget for SSB tabell 07221 — prisindeks for brukte boliger.

Rådata er allerede filtrert til hele landet og alle boligtyper i selve
SSB-kallet (``valueCodes[Region]=TOTAL``, ``valueCodes[Boligtype]=00``), av
samme grunn som Preben-hentingen filtrerer til ett fornavn: mindre å hente,
og valget om *hvilket* utsnitt er like gyldig å ta ved henting som i
clean-laget. Mekanisk lag, lang form: de to statistikkvariablene (indeks og
sesongjustert indeks) står som egne rader, ikke egne kolonner — pivoteringen
hører til i mart.

Kvartalskoden («1992K1») brettes ut til år og kvartalsnummer her, siden det
er en ren typekonvertering og ikke et valg. ``kvartal_indeks`` (år × 4 +
kvartal) finnes ved siden av, fordi mart-laget trenger et sammenlignbart
heltall for å sjekke at to rader faktisk er påfølgende kvartal, ikke bare
påfølgende rader.
"""

from __future__ import annotations

from typing import Any, Final

from statman import jsonstat
from statman.registry import Context, model

RAW_BOLIG: Final[str] = "ssb/07221_bolig"


@model(
    name="clean.boligprisindeks",
    deps=[f"raw:{RAW_BOLIG}"],
    checks=[
        "unique:kvartal_kode,variabel",
        "not_null:kvartal_kode",
        "not_null:variabel",
        "kvartal >= 1 and kvartal <= 4",
    ],
    doc="SSB 07221, hele landet og alle boligtyper. Lang form: kvartal × variabel (indeks, sesongjustert indeks).",
)
def clean_boligprisindeks(ctx: Context) -> Any:
    ctx.register("_bolig", jsonstat.to_frame(ctx.raw_latest(RAW_BOLIG)))
    return ctx.sql("""
        select
            tid                                                as kvartal_kode,
            cast(substr(tid, 1, 4) as integer)                  as aar,
            cast(substr(tid, 6, 1) as integer)                  as kvartal,
            cast(substr(tid, 1, 4) as integer) * 4
                + cast(substr(tid, 6, 1) as integer)            as kvartal_indeks,
            lower(contentscode)                                 as variabel,
            value                                               as verdi,
            status
        from _bolig
        order by kvartal_indeks, variabel
    """)
