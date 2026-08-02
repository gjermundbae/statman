"""clean-laget for den syntetiske kilden: typing og normaliserte navn, ingenting annet."""

from __future__ import annotations

from typing import Any

from statman.registry import Context, model


@model(
    name="clean.kraftpris",
    deps=["raw:synthetic/kraftpris"],
    checks=["unique:month,prisomrade", "not_null:ore_per_kwh", "ore_per_kwh > 0"],
    doc="Månedlig syntetisk kraftpris per prisområde, øre/kWh.",
)
def clean_kraftpris(ctx: Context) -> Any:
    src = ctx.raw_latest("synthetic/kraftpris").as_posix()
    return ctx.sql(f"""
        select
            make_date(
                cast(substr(periode, 1, 4) as int),
                cast(substr(periode, 6, 2) as int),
                1
            )                          as month,
            cast(prisomrade as varchar) as prisomrade,
            cast(ore_per_kwh as double) as ore_per_kwh
        from read_json_auto('{src}')
        where ore_per_kwh is not null
        order by month, prisomrade
    """)


@model(
    name="clean.kpi",
    deps=["raw:synthetic/kpi"],
    checks=["unique:month", "not_null:indeks_2015", "indeks_2015 > 0"],
    doc="Månedlig syntetisk konsumprisindeks, 2015 = 100.",
)
def clean_kpi(ctx: Context) -> Any:
    src = ctx.raw_latest("synthetic/kpi").as_posix()
    return ctx.sql(f"""
        select
            make_date(
                cast(substr(periode, 1, 4) as int),
                cast(substr(periode, 6, 2) as int),
                1
            )                           as month,
            cast(indeks_2015 as double) as indeks_2015
        from read_json_auto('{src}')
        where indeks_2015 is not null
        order by month
    """)
