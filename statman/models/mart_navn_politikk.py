"""mart-laget for navn-mot-politikk: her tas valgene.

To valg betyr noe her.

**Hva som er «borgerlig».** SSBs valgundersøkelse har ti partier/lister. Vi
summerer Høyre, Fremskrittspartiet, Kristelig Folkeparti og Venstre til én
borgerlig blokk. Senterpartiet er *ikke* med: det har i
det aktuelle tidsrommet sittet i regjering med både Ap og med de fire
borgerlige, og regnes ikke entydig til noen blokk over femtiseks år. Det er
en vurdering, ikke en naturlov — kolonnene ``hoyre``, ``frp``, ``krf`` og
``venstre`` står med hver for seg i tabellen, så et annet partiutvalg kan
regnes ut uten å bygge om noe.

**Ingen forskyvning i tid.** Andelen nyfødte gutter med navnet Preben det
året kobles mot borgerlig oppslutning *samme* år — ikke mot barnets
stemmerettsalder, ikke mot foreldrenes fødselsår. Det er den mest
bokstavelige lesningen av hypotesen («perioder med borgerlige meninger»
sammenfaller med fødselsåret), og den som er lettest å etterprøve. En
analyse som i stedet leter etter det forskyvningstallet som gir høyest
korrelasjon, har sluttet å teste en hypotese og begynt å konstruere en.

**Hva som IKKE er fikset her.** 1969 mangler Fremskrittspartiet — partiet
fantes ikke ennå (Anders Langes parti stilte første gang i 1973) — og har
derfor ``borgerlig_andel_pst = null`` i stedet for et tall som undervurderer
blokken. 2025 mangler navnetall: navngivningsår (SSBs metode fra 2021) har
et etterslep, og Preben 2023-2025 er enten undertrykt (færre enn fire
personer) eller ikke ferdig talt opp ennå. Begge hull vises som ``null``,
ikke som null eller som et interpolert tall, og ``brukbar`` i den
sammenstilte tabellen er ``false`` for dem.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

# Partikodene SSB bruker i tabell 09624, for de fire vi regner som borgerlige.
HOYRE: Final[str] = "03"
FRP: Final[str] = "02"
KRF: Final[str] = "04"
VENSTRE: Final[str] = "07"


@model(
    name="mart.navn_preben_aar",
    deps=["clean.navn_preben"],
    checks=[
        "unique:aar",
        "not_null:aar",
        "andel_fodte_pst is null or andel_fodte_pst >= 0",
    ],
    doc="Preben, én rad per år 1880-2025: fødselstall og andel av nyfødte gutter.",
)
def navn_preben_aar(ctx: Context) -> Any:
    return ctx.sql("""
        with bred as (
            select
                aar,
                max(case when variabel = 'personer'       then verdi end) as fodte_gutter,
                max(case when variabel = 'personerprosent' then verdi end) as andel_fodte_pst
            from clean_navn_preben
            group by all
        )
        select aar, fodte_gutter, andel_fodte_pst
        from bred
        order by aar
    """)


@model(
    name="mart.velgere_borgerlig",
    deps=["clean.velgere_parti"],
    checks=[
        "unique:aar",
        "not_null:aar",
        "borgerlig_andel_pst is null or (borgerlig_andel_pst >= 0 and borgerlig_andel_pst <= 100)",
    ],
    doc="Valgår 1969-2025: de fire borgerlige partienes andel av velgerne, samlet.",
)
def velgere_borgerlig(ctx: Context) -> Any:
    return ctx.sql(f"""
        with bred as (
            select
                aar,
                max(case when parti = '{HOYRE}'   then andel_velgere_pst end) as hoyre,
                max(case when parti = '{FRP}'     then andel_velgere_pst end) as frp,
                max(case when parti = '{KRF}'     then andel_velgere_pst end) as krf,
                max(case when parti = '{VENSTRE}' then andel_velgere_pst end) as venstre
            from clean_velgere_parti
            group by all
        )
        select
            aar,
            hoyre,
            frp,
            krf,
            venstre,
            -- null så snart ett av de fire mangler, i stedet for å summere
            -- de tre man har og late som blokken var komplett.
            hoyre + frp + krf + venstre as borgerlig_andel_pst
        from bred
        order by aar
    """)


@model(
    name="mart.preben_borgerlig",
    deps=["mart.velgere_borgerlig", "mart.navn_preben_aar"],
    checks=[
        "unique:aar",
        "not_null:aar",
    ],
    doc="Valgår × Preben-andel samme år, klar for korrelasjon. 'brukbar' sier hvilke rader har begge tall.",
)
def preben_borgerlig(ctx: Context) -> Any:
    return ctx.sql("""
        select
            v.aar,
            n.andel_fodte_pst        as andel_fodte_preben_pst,
            n.fodte_gutter           as fodte_gutter_preben,
            v.borgerlig_andel_pst,
            v.hoyre,
            v.frp,
            v.krf,
            v.venstre,
            (n.andel_fodte_pst is not null and v.borgerlig_andel_pst is not null) as brukbar
        from mart_velgere_borgerlig v
        left join mart_navn_preben_aar n on n.aar = v.aar
        order by v.aar
    """)
