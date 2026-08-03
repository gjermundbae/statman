"""mart-laget for meningsmålinger mot navn: trend i stedet for nivå.

Tre valg betyr noe her, og det siste er hele grunnen til at denne filen
finnes ved siden av ``mart_navn_politikk.py``.

**Bare hele kalenderår.** pollofpolls.no gir ikke et årssnitt direkte —
APIet har ``int=m`` (månedlig), ikke ``int=y``. Årssnittet her er derfor
vårt eget: gjennomsnittet av de månedlige snittene i året. Et år med færre
enn tolv måneder (per nå bare inneværende år, som ikke er ferdig) får
``borgerlig_andel_pst = null`` i stedet for et snitt som ikke er
sammenlignbart med et helt år.

**Samme fire partier som i mart_navn_politikk.py**, samme begrunnelse for
hvorfor Senterpartiet er utelatt — se den fila. Her identifiseres partiene
ved navnet pollofpolls.no bruker i sin egen CSV (``Høyre``, ikke en kode),
fordi det er det kilden gir oss.

**Endring år for år, ikke nivå.** Både Preben-andelen og den borgerlige
oppslutningen har beveget seg i store, langsomme buer over perioden dette
datasettet dekker (2008-2025) — Preben på vei ned det meste av tiden,
blokken likeens fram til 2019. To serier som begge glir nedover vil
korrelere på *nivå* nesten uansett hva de faktisk måler, rett og slett
fordi de deler en retning. Det er ikke en oppdagelse, det er en fallgruve.
Denne modellen regner derfor også ut ``delta_*``: endringen fra året før,
for begge serier. Er det en ekte samvariasjon og ikke bare delt trend, skal
den vise seg i om *endringene* følges at — ikke bare om nivåene gjør det.

``delta_*`` er ``null`` med mindre både i år og i fjor har tall, *og* i
fjor faktisk er året før — ikke bare forrige rad. Uten den sjekken ville et
hull i serien (Preben er undertrykt eller ikke ferdig talt opp for flere år
etter 2021) blitt lest som en étt-års endring når det egentlig er to eller
tre.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

# Partinavnene slik pollofpolls.no selv skriver dem i CSV-header.
HOYRE: Final[str] = "Høyre"
FRP: Final[str] = "Frp"
KRF: Final[str] = "KrF"
VENSTRE: Final[str] = "Venstre"


@model(
    name="mart.meningsmaling_aar",
    deps=["clean.meningsmaling_parti"],
    checks=[
        "unique:aar,parti",
        "not_null:parti",
        "maaneder >= 1 and maaneder <= 12",
        "andel_velgere_pst >= 0",
    ],
    doc="Årssnitt per parti: gjennomsnitt av de månedlige poll-of-polls-tallene.",
)
def meningsmaling_aar(ctx: Context) -> Any:
    return ctx.sql("""
        select
            aar,
            parti,
            avg(andel_velgere_pst) as andel_velgere_pst,
            count(*)               as maaneder
        from clean_meningsmaling_parti
        group by all
        order by aar, parti
    """)


@model(
    name="mart.velgere_borgerlig_meningsmaling",
    deps=["mart.meningsmaling_aar"],
    checks=[
        "unique:aar",
        "not_null:aar",
        "borgerlig_andel_pst is null or (borgerlig_andel_pst >= 0 and borgerlig_andel_pst <= 100)",
    ],
    doc="Årssnitt 2008-: de fire borgerlige partienes oppslutning i meningsmålinger, samlet.",
)
def velgere_borgerlig_meningsmaling(ctx: Context) -> Any:
    return ctx.sql(f"""
        with maaneder_pr_aar as (
            select aar, max(maaneder) as maaneder
            from mart_meningsmaling_aar
            group by aar
        ),
        bred as (
            select
                aar,
                max(case when parti = '{HOYRE}'   then andel_velgere_pst end) as hoyre,
                max(case when parti = '{FRP}'     then andel_velgere_pst end) as frp,
                max(case when parti = '{KRF}'     then andel_velgere_pst end) as krf,
                max(case when parti = '{VENSTRE}' then andel_velgere_pst end) as venstre
            from mart_meningsmaling_aar
            group by all
        )
        select
            b.aar,
            m.maaneder,
            b.hoyre,
            b.frp,
            b.krf,
            b.venstre,
            -- null for år med færre enn tolv måneder i snittet, ikke et
            -- partial-year-gjennomsnitt som ser ut som et helt.
            case when m.maaneder = 12
                 then b.hoyre + b.frp + b.krf + b.venstre
            end as borgerlig_andel_pst
        from bred b
        join maaneder_pr_aar m using (aar)
        order by b.aar
    """)


@model(
    name="mart.preben_trend",
    deps=["mart.velgere_borgerlig_meningsmaling", "mart.navn_preben_aar"],
    checks=[
        "unique:aar",
        "not_null:aar",
    ],
    doc="Preben-andel og borgerlig meningsmålingssnitt, på nivå og som endring år for år.",
)
def preben_trend(ctx: Context) -> Any:
    return ctx.sql("""
        with koblet as (
            select
                v.aar,
                v.maaneder,
                v.borgerlig_andel_pst,
                n.andel_fodte_pst as andel_fodte_preben_pst
            from mart_velgere_borgerlig_meningsmaling v
            left join mart_navn_preben_aar n on n.aar = v.aar
        ),
        med_forrige as (
            select
                *,
                lag(aar)                     over (order by aar) as forrige_aar,
                lag(borgerlig_andel_pst)      over (order by aar) as forrige_borgerlig,
                lag(andel_fodte_preben_pst)   over (order by aar) as forrige_preben
            from koblet
        ),
        deltaer as (
            select
                aar,
                maaneder,
                borgerlig_andel_pst,
                andel_fodte_preben_pst,
                (borgerlig_andel_pst is not null and andel_fodte_preben_pst is not null)
                                              as brukbar_niva,
                case when forrige_aar = aar - 1
                     then borgerlig_andel_pst - forrige_borgerlig
                end as delta_borgerlig_pst,
                case when forrige_aar = aar - 1
                     then andel_fodte_preben_pst - forrige_preben
                end as delta_andel_fodte_preben_pst
            from med_forrige
        )
        select
            *,
            (delta_borgerlig_pst is not null and delta_andel_fodte_preben_pst is not null)
                as brukbar_delta
        from deltaer
        order by aar
    """)
