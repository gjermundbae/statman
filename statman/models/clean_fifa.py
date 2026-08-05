"""clean-laget for FIFA/Coca-Cola Men's World Ranking.

Mekanisk lag: rålaget er allerede én rad per landslag (se
``statman/sources/fifa.py`` for hvordan den kvitteringen ble til). Det
eneste som skjer her er typing, og å skille poengtall FIFA selv markerte
med ``*`` — «beregnet, ikke offisielt stadfestet ennå» for lag som spilte
utenfor det ordinære rankingvinduet — fra de stadfestede.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

RAW_WORLD_RANKING_MEN: Final[str] = "fifa/world_ranking_men"


@model(
    name="clean.fifa_ranking",
    deps=[f"raw:{RAW_WORLD_RANKING_MEN}"],
    checks=[
        "unique:rangering",
        "unique:fifa_kode",
        "not_null:rangering",
        "not_null:fifa_kode",
        "not_null:poeng",
    ],
    doc="FIFA/Coca-Cola Men's World Ranking, én rad per landslag. Gjeldende fra 20. juli 2026.",
)
def clean_fifa_ranking(ctx: Context) -> Any:
    path = ctx.raw_latest(RAW_WORLD_RANKING_MEN)
    return ctx.sql(f"""
        select
            rank::integer                                        as rangering,
            code                                                  as fifa_kode,
            team                                                  as lag,
            regexp_replace(points, '\\*$', '')::double            as poeng,
            points like '%*'                                      as poeng_urevidert,
            case regexp_extract(trend_class, '(\\w+)$')
                when 'positive' then trend_value::integer
                when 'negative' then -trend_value::integer
                else 0
            end                                                   as plasser_siden_forrige,
            regexp_extract(trend_class, '(\\w+)$')                as trend_retning
        from read_json_auto('{path.as_posix()}')
        order by rangering
    """)
