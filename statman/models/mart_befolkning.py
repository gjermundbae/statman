"""mart-laget for befolkning: her tas valgene.

Tre valg betyr noe her.

**Kommuneinndeling.** Vi henter tabellen i SSBs kodeliste
``agg_KommSummerHist`` — «Kommuner 2024, sammenslåtte tidsserier» — så
historikken til sammenslåtte kommuner er summert opp til dagens grenser.
Det løser sammenslåingene i 2018 og 2020, men *ikke* delinger og
grensejusteringer. Ålesund faller fra 67 520 til 58 509 innbyggere mellom
2023 og 2024 fordi Haram ble skilt ut igjen, og det er ikke
befolkningsnedgang.

**Derfor beregner vi grenseavvik.** For hvert kommuneår sammenligner vi
endringen i folkemengden med folketilveksten SSB oppgir. Er de like, har
kommunen samme grenser i begge målingene. Avviket er lik antallet personer
som byttet kommune uten å flytte. Flagget ``sammenlignbar`` er dermed ikke
hentet fra en liste vi må vedlikeholde, men fra tallene selv — og fanger
derfor også grensejusteringer, som ikke gir nytt kommunenummer og ikke
vises i Klass sine endringslister.

**Med en toleranse.** Over femten år har 65 av 357 kommuner *et eller
annet* grenseavvik. De aller fleste er bittesmå: Drammen avga 29 personer
til Øvre Eiker i 2022, som er 0,03 prosent av kommunen. Å kaste Drammen ut
av statistikken for det ville vært å ofre signalet for støyen. Vi krever
derfor ikke at avviket er null, men at det største enkeltavviket er under
``TOLERANSE`` av folketallet. Avviket rapporteres uansett, i
``grenseavvik_sum`` og ``grenseavvik_maks_pst``, så terskelen kan
etterprøves i stedet for å måtte tros.

**Restledd.** Folketilvekst er ikke alltid nøyaktig fødselsoverskudd pluss
nettoinnflytting. Differansen er liten (median 1 person per kommuneår), men
den finnes, og vi tar den med som egen kolonne i stedet for å fordele den
på komponentene eller late som den ikke er der.

**Det denne modellen ikke kan fikse.** Kommuner som ble *delt* i 2020
(Tysfjord, Snillfjord) har en historikk som ikke lar seg tilordne én
kommune i dagens inndeling. SSB legger den i samlekategorien «Delte
kommuner og uoppgitt», som holder rundt 53 000 personer til og med 2019.
De personene finnes altså ikke i kommunetabellen, bare i fylkestabellen.
Derfor er ``mart.befolkning_fylke_aar`` bygget fra fylkesserien direkte og
ikke summert opp fra kommunene — de to summerer seg til ulike tall før
2020, og det er fylkestabellen som er riktig.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

# Antall hele kalenderår vekstmodellen dekker. Folkemengden måles 1. januar,
# så 15 år er avstanden mellom to målinger seksten år fra hverandre i
# tabellen: 1.1.2011 -> 1.1.2026 er veksten gjennom 2011–2025.
PERIODE_AAR: Final[int] = 15

# Hvor stort et enkelt grenseavvik kan være, målt mot folketallet ved
# inngangen til året, før kommunen regnes som usammenlignbar. 0,5 prosent er
# valgt fordi typisk vekst over femten år er rundt ti prosent — en
# grenseendring på en halv prosent kan da flytte vekstanslaget med en
# tjuedel, og ikke mer. Tallet er en vurdering, ikke en naturlov; derfor
# ligger de faktiske avvikene i tabellen ved siden av flagget.
TOLERANSE: Final[float] = 0.005


@model(
    name="mart.befolkning_kommune_aar",
    deps=["clean.befolkning_kommune", "clean.befolkning_fylke"],
    checks=[
        "unique:kommunenummer,aar",
        "not_null:fylke",
        "folkemengde >= 0",
    ],
    doc="Kommune × år: folkemengde 1.1., endringskomponenter, restledd og grenseavvik.",
)
def befolkning_kommune_aar(ctx: Context) -> Any:
    return ctx.sql("""
        with bred as (
            select
                kommunenummer,
                kommune,
                aar,
                max(case when variabel = 'folkemengde'       then verdi end) as folkemengde,
                max(case when variabel = 'fodselsoverskudd'  then verdi end) as fodselsoverskudd,
                max(case when variabel = 'nettoinnflytting'  then verdi end) as nettoinnflytting,
                max(case when variabel = 'folketilvekst'     then verdi end) as folketilvekst
            from clean_befolkning_kommune
            group by all
        ),
        fylker as (
            select distinct fylkesnummer, fylke from clean_befolkning_fylke
        ),
        med_neste as (
            -- Vinduet i eget steg, så det regnes før noe joines på og ikke
            -- kan forveksles med aliasene i sluttselektet.
            select
                *,
                lead(folkemengde) over (partition by kommunenummer order by aar)
                    as folkemengde_neste
            from bred
        )
        select
            b.kommunenummer,
            b.kommune,
            substr(b.kommunenummer, 1, 2)   as fylkesnummer,
            f.fylke,
            b.aar,
            b.folkemengde,
            b.folkemengde_neste,
            b.fodselsoverskudd,
            b.nettoinnflytting,
            b.folketilvekst,
            b.folketilvekst - b.fodselsoverskudd - b.nettoinnflytting
                                            as restledd,
            b.folkemengde_neste - b.folkemengde - b.folketilvekst
                                            as grenseavvik,
            abs(b.folkemengde_neste - b.folkemengde - b.folketilvekst)
                / nullif(b.folkemengde, 0)::double
                                            as grenseavvik_pst,
            -- Ratene måles mot folkemengden ved inngangen til året, ikke mot
            -- et gjennomsnitt. Da er de direkte sammenlignbare med
            -- vekst_pst i periodetabellen, og med hverandre.
            b.folketilvekst / nullif(b.folkemengde, 0)::double
                                            as vekst_pst,
            b.fodselsoverskudd / nullif(b.folkemengde, 0)::double
                                            as fodselsoverskudd_pst,
            b.nettoinnflytting / nullif(b.folkemengde, 0)::double
                                            as nettoinnflytting_pst
        from med_neste b
        left join fylker f on f.fylkesnummer = substr(b.kommunenummer, 1, 2)
        order by b.kommunenummer, b.aar
    """)


@model(
    name="mart.befolkning_fylke_aar",
    deps=["clean.befolkning_fylke"],
    checks=[
        "unique:fylkesnummer,aar",
        "not_null:folkemengde",
        "folkemengde > 0",
    ],
    doc="Fylke × år, samme form som kommunetabellen. Komplett også før 2020.",
)
def befolkning_fylke_aar(ctx: Context) -> Any:
    """Fylkestallene kommer fra fylkesserien, ikke fra en oppsummering av
    kommunene. De to er ikke like: personene i kommuner som ble delt i 2020
    ligger i en samlekategori som ikke er noen kommune, og faller ut når man
    summerer kommunetabellen. Fylkesserien har dem med."""
    return ctx.sql("""
        with bred as (
            select
                fylkesnummer,
                fylke,
                aar,
                max(case when variabel = 'folkemengde'       then verdi end) as folkemengde,
                max(case when variabel = 'fodselsoverskudd'  then verdi end) as fodselsoverskudd,
                max(case when variabel = 'nettoinnflytting'  then verdi end) as nettoinnflytting,
                max(case when variabel = 'folketilvekst'     then verdi end) as folketilvekst
            from clean_befolkning_fylke
            group by all
        )
        select
            fylkesnummer,
            fylke,
            aar,
            folkemengde,
            fodselsoverskudd,
            nettoinnflytting,
            folketilvekst,
            folketilvekst - fodselsoverskudd - nettoinnflytting  as restledd,
            folketilvekst / nullif(folkemengde, 0)::double       as vekst_pst
        from bred
        order by fylkesnummer, aar
    """)


@model(
    name="mart.befolkningsvekst",
    deps=["mart.befolkning_kommune_aar"],
    checks=[
        "unique:kommunenummer",
        "not_null:folkemengde_start",
        # Et hull i årsrekka ville gjort både summene og grenseavviket
        # meningsløse, og det ville ikke vist seg i noe annet tall. Derfor
        # telles årene eksplisitt.
        f"aar_med_stromtall = {PERIODE_AAR}",
        # Bestandsendringen skal være lik summen av strømmene pluss det som
        # kom eller gikk med grenseendringer. Denne holder for *alle*
        # kommuner, også de usammenlignbare, og er derfor en ekte sjekk på
        # at grenseavviket faktisk fanger hele differansen.
        "vekst = folketilvekst_sum + grenseavvik_sum",
    ],
    doc=f"Én rad per kommune: befolkningsvekst over {PERIODE_AAR} år, dekomponert.",
)
def befolkningsvekst(ctx: Context) -> Any:
    return ctx.sql(f"""
        with periode as (
            select
                max(aar)                    as aar_slutt,
                max(aar) - {PERIODE_AAR}    as aar_start
            from mart_befolkning_kommune_aar
            where folkemengde is not null
        ),
        niva as (
            select
                b.kommunenummer,
                b.kommune,
                b.fylkesnummer,
                b.fylke,
                max(case when b.aar = p.aar_start then b.folkemengde end) as folkemengde_start,
                max(case when b.aar = p.aar_slutt then b.folkemengde end) as folkemengde_slutt
            from mart_befolkning_kommune_aar b
            cross join periode p
            group by all
        ),
        strom as (
            -- Strømmene hører til året de skjer i, så siste måleår er ikke med.
            select
                b.kommunenummer,
                sum(b.fodselsoverskudd)           as fodselsoverskudd,
                sum(b.nettoinnflytting)           as nettoinnflytting,
                sum(b.folketilvekst)              as folketilvekst,
                sum(coalesce(b.grenseavvik, 0))   as grenseavvik,
                -- Det største *enkelt*avviket, ikke summen. To grensebytter
                -- i motsatt retning kan nulle hverandre ut i summen uten at
                -- serien er blitt sammenlignbar av den grunn.
                max(coalesce(b.grenseavvik_pst, 0)) as grenseavvik_maks_pst,
                arg_max(b.aar, abs(coalesce(b.grenseavvik, 0)))
                                                  as grenseavvik_maks_aar,
                -- Kommuner som ble dannet av en *delt* kommune i 2020 har
                -- ingen historikk i dagens inndeling i det hele tatt: SSB
                -- oppgir folkemengde 0 for alle årene før. Da er det ingen
                -- grenseavvik å måle relativt — nevneren er null — så de må
                -- telles for seg.
                sum(case when b.folkemengde = 0 then 1 else 0 end)
                                                  as aar_uten_folketall,
                count(b.folketilvekst)            as aar_med_stromtall
            from mart_befolkning_kommune_aar b
            cross join periode p
            where b.aar >= p.aar_start
              and b.aar <  p.aar_slutt
            group by all
        ),
        samlet as (
            select
                p.aar_start,
                p.aar_slutt,
                n.kommunenummer,
                n.kommune,
                n.fylkesnummer,
                n.fylke,
                n.folkemengde_start,
                n.folkemengde_slutt,
                n.folkemengde_slutt - n.folkemengde_start   as vekst,
                s.fodselsoverskudd  as fodselsoverskudd_sum,
                s.nettoinnflytting  as nettoinnflytting_sum,
                s.folketilvekst     as folketilvekst_sum,
                s.folketilvekst - s.fodselsoverskudd - s.nettoinnflytting
                                    as restledd_sum,
                s.grenseavvik       as grenseavvik_sum,
                s.grenseavvik_maks_pst,
                s.grenseavvik_maks_aar,
                s.aar_uten_folketall,
                s.aar_med_stromtall,
                (s.grenseavvik_maks_pst <= {TOLERANSE}) and (s.aar_uten_folketall = 0)
                                    as sammenlignbar
            from niva n
            join strom s using (kommunenummer)
            cross join periode p
        )
        select
            kommunenummer,
            kommune,
            fylkesnummer,
            fylke,
            aar_start,
            aar_slutt,
            folkemengde_start,
            folkemengde_slutt,
            vekst,
            vekst / nullif(folkemengde_start, 0)::double            as vekst_pst,
            fodselsoverskudd_sum,
            nettoinnflytting_sum,
            folketilvekst_sum,
            restledd_sum,
            grenseavvik_sum,
            grenseavvik_maks_pst,
            grenseavvik_maks_aar,
            aar_uten_folketall,
            aar_med_stromtall,
            sammenlignbar,
            -- Rangeringen gjelder bare kommuner med stabile grenser. De andre
            -- får null, så en sortering på rangering aldri blander dem inn.
            case when sammenlignbar
                 then rank() over (partition by sammenlignbar order by
                                   vekst / nullif(folkemengde_start, 0)::double desc)
            end                                                     as rangering
        from samlet
        order by vekst_pst desc nulls last
    """)
