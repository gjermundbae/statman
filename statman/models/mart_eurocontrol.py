"""mart-laget for EUROCONTROL/PRB-tallene — valgene som ikke hører i clean.

To valg tas her, begge begrunnet i hva ``clean.eurocontrol_kapasitet``
faktisk dekker (se den modulens docstring for hvorfor dataene er så ujevne):

**Bodø ACC er valgt som den gjennomgående kontrollsentralen** for
produktivitetsserien, fordi det er den eneste av de tre som har et tall for
fire av fem år (2020, 2021, 2023, 2024 — 2022 mangler også for Bodø). Oslo
og Stavanger har bare ett løst tall hver i hele perioden og kan ikke bære en
tidsserie. Det gjør ikke Bodø representativ for alle tre — bare best belyst
i akkurat dette datamaterialet.

**Bemanningen (ATCO i operativ tjeneste) vises bare for 2024**, det eneste
året rapporten oppgir et grunntall og ikke bare et avvik fra planen. Det er
et øyeblikksbilde, ikke en trend.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

BODO: Final[str] = "Bodo"


@model(
    name="mart.eurocontrol_bodo_arbeidsbelastning",
    deps=["clean.eurocontrol_kapasitet", "clean.eurocontrol_trafikk_norge"],
    checks=["unique:aar", "min_rows:1", "ifr_bevegelser_norge_1000 > 0"],
    doc="Bodø ACC — sektortimer og produktivitet — ved siden av Norges samlede IFR-trafikk, per år.",
)
def mart_eurocontrol_bodo_arbeidsbelastning(ctx: Context) -> Any:
    """2019 er med for trafikkens del (baseline-året alle fem rapportene siterer likt),
    men har naturlig ingen Bodø-kapasitetstall — kilden dekker bare 2020-2024 der."""
    return ctx.sql(f"""
        select
            t.aar                                       as aar,
            t.ifr_bevegelser_1000                        as ifr_bevegelser_norge_1000,
            k.sektortimer                                as bodo_sektortimer,
            k.ifr_bevegelser_per_sektortime               as bodo_ifr_per_sektortime
        from clean_eurocontrol_trafikk_norge t
        left join clean_eurocontrol_kapasitet k
            on k.aar = t.aar and k.acc = '{BODO}'
        order by t.aar
    """)


@model(
    name="mart.eurocontrol_bemanning_2024",
    deps=["clean.eurocontrol_kapasitet"],
    checks=["min_rows:1", "unique:acc", "not_null:atco_ops", "atco_plan >= atco_ops"],
    doc="ATCO i operativ tjeneste per kontrollsentral, faktisk mot plan, 2024 — eneste år med grunntall.",
)
def mart_eurocontrol_bemanning_2024(ctx: Context) -> Any:
    return ctx.sql("""
        select
            acc                                          as acc,
            acc_navn                                      as acc_navn,
            acc_kode                                      as acc_kode,
            atco_ops                                      as atco_ops,
            atco_plan                                     as atco_plan,
            atco_plan - atco_ops                          as atco_under_plan
        from clean_eurocontrol_kapasitet
        where aar = 2024 and atco_ops is not null
        order by acc
    """)
