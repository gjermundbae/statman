"""mart-laget for styringsrenten mot boligprisene.

Tre modeller, tre nivåer av valg.

**mart.rente_kvartal** er mekanisk: styringsrenten er notert per virkedag,
og kvartalssnittet er bare et gjennomsnitt av de virkedagene. ``dager``
følger med for å kunne se at et kvartal faktisk har nok noteringer bak seg
til at snittet betyr noe.

**mart.boligpris_kvartal** pivoterer clean-laget fra lang til bred form —
samme valg som ``mart_navn_politikk.navn_preben_aar`` tar, av samme grunn.

**mart.rente_bolig_kvartal** er der spørsmålet stilles, og der to valg
betyr noe:

*Sesongjustert indeks brukes til endringstallet, ikke den rå.* Boligsalg har
et ekte sesongmønster (mer aktivitet om våren og høsten enn midtvinters), så
et kvartal-mot-kvartal-tall regnet på den ujusterte indeksen ville for det
meste målt årstiden, ikke renta. Den rå indeksen brukes fortsatt til
nivåbildet over hele perioden, siden SSBs sesongjustering først finnes fra
2005K1 — elleve år kortere enn styringsrenteserien.

*Endring regnes bare mellom faktisk påfølgende kvartal.* Samme mønster som
``mart_meningsmaling_politikk.preben_trend``: ``lag()`` sammenlignes mot
``kvartal_indeks - 1``, ikke bare mot forrige rad, så et eventuelt hull i én
av seriene aldri blir lest som én kvartals endring når det egentlig er flere
(det finnes ikke noe slikt hull i disse to seriene i dag, men sjekken koster
ingenting og gjør antakelsen eksplisitt).
"""

from __future__ import annotations

from typing import Any

from statman.registry import Context, model


@model(
    name="mart.rente_kvartal",
    deps=["clean.styringsrente"],
    checks=[
        "unique:kvartal_kode",
        "not_null:kvartal_kode",
        "not_null:rente_snitt_pst",
        "dager >= 1",
    ],
    doc="Styringsrenten, ett kvartalssnitt per kvartal fra 1991, regnet av virkedagsnoteringene.",
)
def rente_kvartal(ctx: Context) -> Any:
    return ctx.sql("""
        with kvart as (
            select
                dato,
                extract(year from dato)::integer                    as aar,
                (extract(month from dato)::integer - 1) // 3 + 1    as kvartal,
                rente_pst
            from clean_styringsrente
        )
        select
            aar,
            kvartal,
            aar * 4 + kvartal                       as kvartal_indeks,
            aar::varchar || 'K' || kvartal::varchar  as kvartal_kode,
            avg(rente_pst)                           as rente_snitt_pst,
            count(*)                                 as dager
        from kvart
        group by all
        order by kvartal_indeks
    """)


@model(
    name="mart.boligpris_kvartal",
    deps=["clean.boligprisindeks"],
    checks=[
        "unique:kvartal_kode",
        "not_null:kvartal_kode",
        "not_null:boligindeks",
        "boligindeks_sesjustert is null or boligindeks_sesjustert > 0",
    ],
    doc="Prisindeks for brukte boliger, ett kvartal per rad: rå og sesongjustert (fra 2005K1).",
)
def boligpris_kvartal(ctx: Context) -> Any:
    return ctx.sql("""
        select
            kvartal_kode,
            aar,
            kvartal,
            kvartal_indeks,
            max(case when variabel = 'boligindeks'          then verdi end) as boligindeks,
            max(case when variabel = 'sesjustboligindeks'    then verdi end) as boligindeks_sesjustert
        from clean_boligprisindeks
        group by all
        order by kvartal_indeks
    """)


@model(
    name="mart.rente_bolig_kvartal",
    deps=["mart.rente_kvartal", "mart.boligpris_kvartal"],
    checks=[
        "unique:kvartal_kode",
        "not_null:kvartal_kode",
    ],
    doc="Styringsrente × boligprisindeks per kvartal, på nivå og som endring fra forrige kvartal.",
)
def rente_bolig_kvartal(ctx: Context) -> Any:
    return ctx.sql("""
        with koblet as (
            select
                b.kvartal_kode,
                b.aar,
                b.kvartal,
                b.kvartal_indeks,
                r.rente_snitt_pst,
                b.boligindeks,
                b.boligindeks_sesjustert
            from mart_boligpris_kvartal b
            left join mart_rente_kvartal r using (kvartal_kode)
        ),
        med_forrige as (
            select
                *,
                lag(kvartal_indeks)         over (order by kvartal_indeks) as forrige_indeks,
                lag(rente_snitt_pst)        over (order by kvartal_indeks) as forrige_rente,
                lag(boligindeks_sesjustert) over (order by kvartal_indeks) as forrige_bolig_sesjustert
            from koblet
        )
        select
            kvartal_kode,
            aar,
            kvartal,
            kvartal_indeks,
            rente_snitt_pst,
            boligindeks,
            boligindeks_sesjustert,
            (rente_snitt_pst is not null and boligindeks is not null) as brukbar_niva,
            case when forrige_indeks = kvartal_indeks - 1
                 then rente_snitt_pst - forrige_rente
            end as delta_rente_pp,
            case when forrige_indeks = kvartal_indeks - 1
                      and boligindeks_sesjustert is not null
                      and forrige_bolig_sesjustert is not null
                 then boligindeks_sesjustert / forrige_bolig_sesjustert - 1
            end as endring_bolig_kvartal_pst
        from med_forrige
        order by kvartal_indeks
    """)
