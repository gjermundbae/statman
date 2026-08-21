"""Det norske arbeidsmarkedet, ett rad per yrke.

Kobler seks utsnitt av SSBs yrkesstatistikk til én analyseklar tabell med
407 rader — de fireside yrkene i STYRK-08. Valgene som tas her, og hvorfor:

**Grainet er fireside STYRK-08, og partisjonen er eksakt.** De 407 yrkene
summerer seg til nøyaktig det SSB publiserer på ``0-9`` («Alle yrker») både
i start- og sluttkvartalet. Det er ikke en tilfeldighet, det er en
egenskap ved klassifikasjonen — og det er sjekken som gjør et flisediagram
forsvarlig. En flise-figur påstår at flatene *er* helheten; er summen bare
omtrent totalen, er påstanden feil uten at figuren ser feil ut.

**Medianlønn på 0 er ikke en lønn.** SSB skriver 0 der det ikke er noen å
regne median for — det gjelder åtte kjønnsdelte celler i de minste yrkene.
Vi gjør dem til null. En nullkrone som får være med, drar enhver
gjennomsnitts- eller ytterpunktsliste med seg.

**Vekst regnes bare der den betyr noe.** ``sammenlignbar`` krever minst
:data:`MINSTE_YRKE` lønnstakere i *begge* endene av perioden, og at yrket
ikke ligger i hovedgruppe 0. Begge deler er én regel hver:

* Under et par hundre ansatte flytter én arbeidsgivers omorganisering
  prosenten mer enn arbeidsmarkedet gjør. Terskelen holder 99 prosent av
  lønnstakerne inne, og er dermed ikke det som avgjør noen av funnene —
  se metodeavsnittet i sakspakken, som regner ut følsomheten.
* Hovedgruppe 0 er «Militære yrker og uoppgitt», og ingen av delene tåler
  en tiårsserie. Forsvaret innførte spesialistordningen (OR/OF) i 2016, og
  omkodingen alene sender «Befal med sersjant grad» opp 365 prosent og
  «Offiserer fra fenrik og høyere grad» ned 51. Det er en reform i
  kodeverket, ikke i arbeidsmarkedet. «Uoppgitt» er på sin side ikke et
  yrke i det hele tatt, men de som mangler yrkeskode — en gruppe som selv
  falt fra 19 600 til 7 600 fordi registreringen ble bedre.

Yrkene som holdes utenfor rangeringen ligger fortsatt i tabellen, og
fortsatt i flisediagrammet. De er en del av arbeidsmarkedet; de er bare
ikke noe man kan regne tiårsvekst for.
"""

from __future__ import annotations

from typing import Any, Final

from statman.registry import Context, model

# Perioden. Samme kvartal i hver ende, så sesongvariasjon ikke telles som
# vekst — antall lønnstakere svinger systematisk gjennom året.
PERIODE_AAR: Final[int] = 10

# Nedre grense for å bli rangert på prosentvekst. Se moduldocstringen.
MINSTE_YRKE: Final[int] = 500

# Hovedgruppa som holdes utenfor rangeringen: militære yrker og uoppgitt.
UTENFOR_HOVEDGRUPPE: Final[str] = "0"

# Kvartalsskiftet SSB selv merker tabellen med: «Fra 4. kvartal 2024 til 1.
# kvartal 2025 har kvalitetsforbedringer i innrapporteringen medført større
# endringer i tabellene med yrke. […] Store endringer mellom disse periodene
# bør tolkes med forsiktighet.» Vi kan ikke rette det, men vi kan måle hvor
# mye av en tiårsendring som skjedde akkurat der, og la sakspakken si det.
BRUDD_FRA: Final[str] = "2024K4"
BRUDD_TIL: Final[str] = "2025K1"


@model(
    name="mart.arbeidsmarked_yrke",
    deps=[
        "clean.styrk",
        "clean.yrke_kvartal",
        "clean.yrke_siste",
        "clean.yrke_kjonn",
        "clean.yrke_alder",
        "clean.yrke_sykefravaer",
        "mart.arbeidsmarked_lonn_kvartal",
    ],
    checks=[
        "unique:yrke",
        "min_rows:1",
        "not_null:yrke_navn",
        "not_null:hovedgruppe_navn",
        "length(yrke) = 4",
        # Flisediagrammets grunnforutsetning: hver flate har en positiv
        # eller null størrelse, og ingen mangler.
        "lonnstakere >= 0",
        # En median på null kroner skal være fjernet, ikke beholdt. Det
        # samme gjelder en snittalder og en arbeidstid på null.
        "median_lonn is null or median_lonn > 0",
        "gjennomsnittsalder is null or gjennomsnittsalder > 0",
        "avtalt_arbeidstid is null or avtalt_arbeidstid > 0",
        # Null er tillatt, og betyr noe: sju av de 407 yrkene har ingen
        # lønnstakere igjen i det hele tatt, og en andel av null personer
        # er ikke null prosent — den finnes ikke. De blir flater uten
        # areal i figuren, og faller ut av enhver andelsberegning.
        "kvinneandel is null or kvinneandel between 0 and 1",
        "andel_55plus is null or andel_55plus between 0 and 1",
        # Kjønnene og aldersbåndene skal dele opp nøyaktig den samme
        # bestanden som totalen. Er de ikke det, har vi koblet feil kvartal.
        "kvinner + menn = lonnstakere",
        "under_40 + fra_40_til_54 + fra_55 = lonnstakere",
        # Prisene steg over perioden, så reallønnsveksten må være lavere enn
        # den nominelle i hvert eneste yrke. Er den ikke det, er deflatoren
        # koblet på feil kvartal — den feilen gir ellers tall som ser helt
        # rimelige ut.
        "reallonn_vekst_pst is null or reallonn_vekst_pst < lonn_vekst_pst",
    ],
    doc="Ett rad per fireside STYRK-08-yrke: bestand, lønn, kjønn, alder, sykefravær og tiårsvekst.",
)
def mart_arbeidsmarked_yrke(ctx: Context) -> Any:
    return ctx.sql(f"""
        with grenser as (
            select
                max(kvartal)                                          as kvartal_slutt,
                (cast(substr(max(kvartal), 1, 4) as integer) - {PERIODE_AAR})
                    || substr(max(kvartal), 5, 2)                      as kvartal_start
            from clean_yrke_kvartal
        ),
        bestand as (
            select
                k.yrke,
                max(case when k.kvartal = g.kvartal_slutt then k.lonnstakere end) as lonnstakere,
                max(case when k.kvartal = g.kvartal_start then k.lonnstakere end) as lonnstakere_start
            from clean_yrke_kvartal k, grenser g
            where k.kvartal in (g.kvartal_start, g.kvartal_slutt)
            group by k.yrke
        ),
        siste as (
            select
                yrke,
                any_value(yrke_navn)                                            as yrke_navn,
                max(case when variabel = 'medianmndlonn' then verdi end)         as median_lonn,
                max(case when variabel = 'gjsnalder'     then verdi end)         as gjennomsnittsalder,
                max(case when variabel = 'gjavtarbtid'   then verdi end)         as avtalt_arbeidstid
            from clean_yrke_siste
            group by yrke
        ),
        kjonn as (
            select
                yrke,
                max(case when kjonn = 'kvinner' and variabel = 'lonsstakere'   then verdi end) as kvinner,
                max(case when kjonn = 'menn'    and variabel = 'lonsstakere'   then verdi end) as menn,
                max(case when kjonn = 'kvinner' and variabel = 'medianmndlonn' then verdi end) as lonn_kvinner,
                max(case when kjonn = 'menn'    and variabel = 'medianmndlonn' then verdi end) as lonn_menn
            from clean_yrke_kjonn
            group by yrke
        ),
        alder as (
            select
                yrke,
                max(case when aldersgruppe = '0-39'  then lonnstakere end) as under_40,
                max(case when aldersgruppe = '40-54' then lonnstakere end) as fra_40_til_54,
                max(case when aldersgruppe = '55+'   then lonnstakere end) as fra_55
            from clean_yrke_alder
            group by yrke
        ),
        sykefravaer as (
            select yrke, aar as sykefravaer_aar, sykefravaer_pst
            from clean_yrke_sykefravaer
            qualify row_number() over (partition by yrke order by aar desc) = 1
        ),
        -- Lønna i hver ende av perioden, nominelt og i faste kroner. Samme
        -- kvartaler som bestanden måles mellom, så de to endringene gjelder
        -- nøyaktig samme tidsrom.
        lonnsutvikling as (
            select
                l.yrke,
                max(case when l.kvartal = g.kvartal_slutt then l.median_lonn_nominell end) as lonn_slutt,
                max(case when l.kvartal = g.kvartal_start then l.median_lonn_nominell end) as lonn_start,
                max(case when l.kvartal = g.kvartal_slutt then l.median_lonn_realt end)    as reallonn_slutt,
                max(case when l.kvartal = g.kvartal_start then l.median_lonn_realt end)    as reallonn_start
            from mart_arbeidsmarked_lonn_kvartal l, grenser g
            where l.kvartal in (g.kvartal_start, g.kvartal_slutt)
            group by l.yrke
        ),
        -- Hvor mye av bestandsendringen som skjedde i det ene kvartalsskiftet
        -- SSB selv ber om at tolkes med forsiktighet. Se BRUDD_FRA/BRUDD_TIL.
        bruddkvartal as (
            select
                yrke,
                max(case when kvartal = '{BRUDD_TIL}'  then lonnstakere end)
                    - max(case when kvartal = '{BRUDD_FRA}' then lonnstakere end) as endring_bruddkvartal
            from clean_yrke_kvartal
            where kvartal in ('{BRUDD_FRA}', '{BRUDD_TIL}')
            group by yrke
        )
        select
            y.kode                                              as yrke,
            s.yrke_navn                                         as yrke_navn,
            substr(y.kode, 1, 1)                                as hovedgruppe,
            h.navn                                              as hovedgruppe_navn,
            substr(y.kode, 1, 2)                                as yrkesgruppe,
            yg.navn                                             as yrkesgruppe_navn,

            cast(b.lonnstakere as bigint)                       as lonnstakere,
            cast(b.lonnstakere_start as bigint)                 as lonnstakere_start,
            cast(b.lonnstakere - b.lonnstakere_start as bigint) as vekst_antall,
            -- Null der utgangspunktet er null: en vekst fra ingen ansatte er
            -- ikke en prosent, uansett hvor mange som kom til.
            case when b.lonnstakere_start > 0
                 then b.lonnstakere / cast(b.lonnstakere_start as double) - 1
            end                                                 as vekst_pst,

            -- Reallønn: samme kvartaler som bestanden, deflatert med KPI.
            -- Null der lønna mangler i én av endene — en reallønnsendring
            -- krever to målinger, og halvparten av et forhold er ingenting.
            lu.lonn_start                                       as median_lonn_start,
            lu.reallonn_start                                   as reallonn_start,
            lu.reallonn_slutt                                   as reallonn_slutt,
            case when lu.lonn_start > 0
                 then lu.lonn_slutt / lu.lonn_start - 1
            end                                                 as lonn_vekst_pst,
            case when lu.reallonn_start > 0
                 then lu.reallonn_slutt / lu.reallonn_start - 1
            end                                                 as reallonn_vekst_pst,

            cast(bk.endring_bruddkvartal as bigint)             as endring_bruddkvartal,

            -- Se moduldocstringen: kildens 0 betyr «ingen å regne på».
            nullif(s.median_lonn, 0)                            as median_lonn,
            nullif(k.lonn_kvinner, 0)                           as median_lonn_kvinner,
            nullif(k.lonn_menn, 0)                              as median_lonn_menn,
            -- Samme regel som over, og av samme grunn: begge er
            -- gjennomsnitt over personer som har yrket, og kilden skriver 0
            -- der det ikke er noen igjen. Uten nullif havner de fire tomme
            -- yrkene på det laveste trinnet i figuren — farget som «under
            -- 38 år» og «under 20 t/uke», som om de var målt.
            nullif(s.gjennomsnittsalder, 0)                     as gjennomsnittsalder,
            nullif(s.avtalt_arbeidstid, 0)                      as avtalt_arbeidstid,

            cast(k.kvinner as bigint)                           as kvinner,
            cast(k.menn as bigint)                              as menn,
            -- nullif, ikke bare en cast: 0/0 er NaN i IEEE-flyttall, og en
            -- NaN sklir gjennom «is null» og havner i figuren som et hull
            -- ingen sjekk fanget.
            k.kvinner / nullif(cast(b.lonnstakere as double), 0) as kvinneandel,

            cast(a.under_40 as bigint)                          as under_40,
            cast(a.fra_40_til_54 as bigint)                     as fra_40_til_54,
            cast(a.fra_55 as bigint)                            as fra_55,
            a.fra_55 / nullif(cast(b.lonnstakere as double), 0) as andel_55plus,

            f.sykefravaer_pst                                   as sykefravaer_pst,
            f.sykefravaer_aar                                   as sykefravaer_aar,

            b.lonnstakere_start >= {MINSTE_YRKE}
                and b.lonnstakere >= {MINSTE_YRKE}
                and substr(y.kode, 1, 1) <> '{UTENFOR_HOVEDGRUPPE}' as sammenlignbar,

            g.kvartal_start                                     as kvartal_start,
            g.kvartal_slutt                                     as kvartal_slutt
        from clean_styrk y
        cross join grenser g
        join siste       s  on s.yrke = y.kode
        join bestand     b  on b.yrke = y.kode
        join clean_styrk h  on h.kode = substr(y.kode, 1, 1)
        join clean_styrk yg on yg.kode = substr(y.kode, 1, 2)
        left join kjonn          k  on k.yrke = y.kode
        left join alder          a  on a.yrke = y.kode
        left join sykefravaer    f  on f.yrke = y.kode
        left join lonnsutvikling lu on lu.yrke = y.kode
        left join bruddkvartal   bk on bk.yrke = y.kode
        where y.nivaa = 4
        order by b.lonnstakere desc, y.kode
    """)


@model(
    name="mart.arbeidsmarked_lonn_kvartal",
    deps=["clean.styrk", "clean.yrke_lonn_kvartal", "mart.konsumpris_kvartal"],
    checks=[
        "unique:yrke,kvartal",
        "min_rows:1",
        "not_null:yrke_navn",
        "length(yrke) = 4",
        "median_lonn_nominell > 0",
        "median_lonn_realt > 0",
        # Referansekvartalet er det eneste der de to er like. Er de like
        # andre steder også, er deflatoren ikke koblet på.
        "kvartal <> kvartal_referanse or abs(median_lonn_realt - median_lonn_nominell) < 0.005",
    ],
    doc="Median månedslønn per fireside yrke og kvartal, nominelt og i faste kroner.",
)
def mart_arbeidsmarked_lonn_kvartal(ctx: Context) -> Any:
    """Lønnsserien deflatert med KPI.

    Nullene fra kilden faller ut her og ikke i clean: en median på null
    kroner er ikke en lønn, og deflatert blir den fortsatt null. Å la den
    stå ville gjort en tom celle til et datapunkt på bunnen av enhver
    reallønnsgraf.

    Kvartaler uten fullstendig KPI faller ut med koblingen — det er en
    innerjoin med vilje. Å deflatere med en ufullstendig indeks ville gitt
    et tall som ser ut som en reallønnsendring uten å være det.
    """
    return ctx.sql("""
        select
            l.yrke                                      as yrke,
            l.yrke_navn                                 as yrke_navn,
            l.kvartal                                   as kvartal,
            l.median_lonn                               as median_lonn_nominell,
            k.kpi                                       as kpi,
            l.median_lonn * k.deflator_siste            as median_lonn_realt,
            k.kvartal_referanse                         as kvartal_referanse
        from clean_yrke_lonn_kvartal l
        join clean_styrk y on y.kode = l.yrke and y.nivaa = 4
        join mart_konsumpris_kvartal k on k.kvartal = l.kvartal
        where l.median_lonn > 0
        order by l.yrke, l.kvartal
    """)


@model(
    name="mart.arbeidsmarked_reallonn_gruppe",
    deps=["clean.styrk", "clean.yrke_kvartal", "mart.arbeidsmarked_lonn_kvartal"],
    checks=[
        "unique:hovedgruppe,kvartal",
        "min_rows:1",
        "not_null:hovedgruppe_navn",
        "reallonn_indeks > 0",
        "yrker > 0",
    ],
    doc="Reallønnsindeks per hovedgruppe og kvartal, med faste vekter fra startkvartalet.",
)
def mart_arbeidsmarked_reallonn_gruppe(ctx: Context) -> Any:
    """Reallønn per hovedgruppe, som indeks med **faste vekter**.

    To valg bærer denne tabellen, og begge er der for å svare på ett
    spørsmål: *endret lønna seg, eller endret det seg hvem som jobber her?*

    **Vektene er låst til startkvartalet.** Et gjennomsnitt med løpende
    vekter blander de to sammen: en gruppe der lavtlønte yrker vokser fort
    får fallende «snittlønn» selv om hvert eneste yrke i den fikk påslag.
    Med faste vekter måler indeksen bare det første.

    **Utvalget er yrker med publisert medianlønn i alle kvartaler.** Et yrke
    som dukker opp midtveis ville ellers flyttet indeksen den dagen det kom,
    med et hopp som ser ut som en lønnsendring. Prisen er at de minste
    yrkene faller ut — de er de samme som mangler median.

    Gruppa ``alle`` er den samme regningen over hele utvalget, ikke snittet
    av de ni gruppene. De to er ikke like når gruppene er ulike store.
    """
    return ctx.sql("""
        with komplett as (
            -- Yrker med lønn i hvert eneste kvartal serien dekker.
            select yrke
            from mart_arbeidsmarked_lonn_kvartal
            group by yrke
            having count(*) = (select count(distinct kvartal) from mart_arbeidsmarked_lonn_kvartal)
        ),
        start as (
            -- Samme startkvartal som resten av saken: samme kvartal ti år
            -- før det siste. Basisen må ligge i samme sesong som den siste
            -- målingen, ellers starter indeksen i en bølgedal og alt ser ut
            -- til å ha steget. Lønn svinger ~2 indekspoeng gjennom året.
            select
                (cast(substr(max(kvartal), 1, 4) as integer) - """ + str(PERIODE_AAR) + """)
                    || substr(max(kvartal), 5, 2) as kvartal_start
            from mart_arbeidsmarked_lonn_kvartal
        ),
        vekt as (
            -- Bestanden i startkvartalet, låst. Yrker uten lønnstakere da
            -- har ingen vekt å bidra med.
            select k.yrke, k.lonnstakere as vekt
            from clean_yrke_kvartal k, start s
            where k.kvartal = s.kvartal_start
              and k.yrke in (select yrke from komplett)
              and k.lonnstakere > 0
        ),
        merket as (
            select
                l.kvartal,
                l.median_lonn_realt,
                v.vekt,
                substr(l.yrke, 1, 1) as hovedgruppe
            from mart_arbeidsmarked_lonn_kvartal l
            join vekt v on v.yrke = l.yrke
        ),
        -- Hver gruppe, og hele utvalget under nøkkelen 'alle'.
        oppdelt as (
            select hovedgruppe, kvartal, median_lonn_realt, vekt from merket
            union all
            select 'alle' as hovedgruppe, kvartal, median_lonn_realt, vekt from merket
        ),
        snitt as (
            select
                hovedgruppe,
                kvartal,
                sum(median_lonn_realt * vekt) / sum(vekt) as reallonn,
                count(*)                                 as yrker,
                sum(vekt)                                as vekt
            from oppdelt
            group by 1, 2
        ),
        basis as (
            select s.hovedgruppe, s.reallonn as reallonn_basis
            from snitt s, start st
            where s.kvartal = st.kvartal_start
        )
        select
            s.hovedgruppe                                   as hovedgruppe,
            coalesce(h.navn, 'Alle yrker')                  as hovedgruppe_navn,
            s.kvartal                                       as kvartal,
            s.reallonn                                      as reallonn,
            s.reallonn / b.reallonn_basis * 100             as reallonn_indeks,
            cast(s.yrker as integer)                        as yrker,
            cast(s.vekt as bigint)                          as lonnstakere_vekt
        from snitt s
        join basis b on b.hovedgruppe = s.hovedgruppe
        left join clean_styrk h on h.kode = s.hovedgruppe and h.nivaa = 1
        order by s.hovedgruppe, s.kvartal
    """)


@model(
    name="mart.arbeidsmarked_hovedgruppe_kvartal",
    deps=["clean.styrk", "clean.yrke_kvartal"],
    checks=[
        "unique:hovedgruppe,kvartal",
        "min_rows:1",
        "not_null:hovedgruppe_navn",
        "lonnstakere > 0",
        "length(hovedgruppe) = 1",
    ],
    doc="Lønnstakere per STYRK-hovedgruppe og kvartal, summert opp fra de 407 yrkene.",
)
def mart_arbeidsmarked_hovedgruppe_kvartal(ctx: Context) -> Any:
    """Hovedgruppene over tid.

    Summert opp fra fireside yrker og ikke hentet fra SSBs egne
    ensifrede koder, av samme grunn som at kommunesaken tar fylkestall fra
    fylkesserien: kildens ensifrede nivå er ikke komplett. Tabell 11658
    slår sammen militære yrker og høyskoleyrker til én kode ``3_01-03``,
    så to av de ti hovedgruppene finnes ikke der. Summen over yrkene har
    dem, og summerer seg til den samme totalen.
    """
    return ctx.sql("""
        select
            substr(k.yrke, 1, 1)      as hovedgruppe,
            h.navn                    as hovedgruppe_navn,
            k.kvartal                 as kvartal,
            sum(k.lonnstakere)        as lonnstakere
        from clean_yrke_kvartal k
        join clean_styrk y on y.kode = k.yrke and y.nivaa = 4
        join clean_styrk h on h.kode = substr(k.yrke, 1, 1)
        group by 1, 2, 3
        having sum(k.lonnstakere) > 0
        order by hovedgruppe, kvartal
    """)


@model(
    name="mart.arbeidsmarked_yrke_aar",
    deps=[
        "clean.styrk",
        "clean.yrke_kvartal",
        "clean.yrke_kjonn_kvartal",
        "clean.yrke_trekk_kvartal",
        "clean.yrke_sykefravaer",
        "clean.yrke_lonn_aar",
        "mart.arbeidsmarked_lonn_kvartal",
    ],
    checks=[
        "unique:yrke,aar",
        "min_rows:1",
        "not_null:yrke_navn",
        "length(yrke) = 4",
        "lonnstakere >= 0",
        # De samme reglene som i øyeblikksbildet, år for år. En median, en
        # snittalder og en arbeidstid på null er kildens måte å si «ingen å
        # regne over», og skal være null her — ikke et målt nullpunkt.
        "median_lonn is null or median_lonn > 0",
        "reallonn is null or reallonn > 0",
        "gjennomsnittsalder is null or gjennomsnittsalder > 0",
        "avtalt_arbeidstid is null or avtalt_arbeidstid > 0",
        "kvinneandel is null or kvinneandel between 0 and 1",
        "sykefravaer_pst is null or sykefravaer_pst between 0 and 30",
        # Kjønnene skal dele opp nøyaktig den samme bestanden som totalen, i
        # hvert eneste årspunkt. Er de ikke det, er kjønnsserien koblet på
        # feil kvartal — en feil som ellers gir kvinneandeler som ser helt
        # rimelige ut.
        "coalesce(kvinner, 0) + coalesce(menn, 0) = lonnstakere",
        # Årspunktet må ligge i det året det sier det gjør. Uten den kan en
        # feilkobling i `punkter` gi et 2019-kvartal merket som 2020, og
        # ingenting annet i tabellen ville sett galt ut.
        "kvartal = cast(aar as varchar) || substr(kvartal, 5, 2)",
    ],
    doc="Ett rad per yrke og årspunkt: bestand, lønn, reallønn, kjønn, alder, arbeidstid og sykefravær.",
)
def mart_arbeidsmarked_yrke_aar(ctx: Context) -> Any:
    """Yrkene år for år — grunnlaget for tidslinja leseren kan dra i.

    Dette er den samme tabellen som ``mart.arbeidsmarked_yrke``, men målt
    i hvert av årspunktene i stedet for bare i endene. Tre valg bærer den:

    **Ett årspunkt per år, i samme kvartal.** Serien fra SSB er kvartalsvis,
    og et punkt per kvartal ville gitt leseren 42 håndtaksposisjoner i
    stedet for elleve. Det er ikke først og fremst et spørsmål om plass.
    Bestanden svinger systematisk gjennom året, og med fritt valgte
    kvartaler kan leseren stille inn en «endring» som i sin helhet er
    sesong — 2019K2 mot 2024K4 leses som en trend. Ankeret er kvartalet i
    den siste målingen, det samme som resten av saken bruker, slik at hver
    avlesning tidslinja kan lage følger nøyaktig den regelen artikkelen
    selv følger. Se ``PERIODE_AAR`` og moduldocstringen over.

    **Hull forblir hull — men ett av dem har en reserve.** Et yrke som ikke
    hadde publisert medianlønn i kvartalsserien (11658) får null der, ikke
    fjorårets tall og ikke et interpolert — med ett unntak: finnes tallet i
    stedet i den årlige tabellen (11418, ``clean.yrke_lonn_aar``), brukes
    det. De to tabellene undertrykker ulikt — samme yrke kan mangle
    medianlønn i ni av ti kvartaler og likevel ha den i seks av ti år — og
    reserven fyller nettopp den forskjellen, ikke noe mer. Den er en annen
    referansemåned og alle sektorer samlet, så et yrke som bytter mellom de
    to kildene fra ett år til det neste kan hoppe litt av en grunn som ikke
    er en lønnsendring; det er verdt å vite, ikke verdt å la stå usett.
    Reallønna beholder hullet uansett — den deflaterte reserven finnes
    ikke, og skal ikke regnes ut her. Der ingen av de to har et tall,
    skraverer figuren det, og skraveringen er en opplysning: SSB publiserer
    ikke median for de minste yrkene, og hvilke yrker som er små endrer seg.

    **Sykefraværet er årlig og ligger et år etter.** Tabell 14789 er ikke
    kvartalsvis, så årspunktet kobles på kalenderåret. Det siste
    årspunktet har derfor ingen sykefraværsmåling ennå. Det er ikke en
    feil, og det skal ikke fylles inn; laget oppgir selv hvor langt det
    rekker, og tidslinja viser resten av skinna som utenfor rekkevidde.
    """
    return ctx.sql("""
        with anker as (
            -- Kvartalsnummeret i den siste målingen. Alle årspunkter tas
            -- fra dette kvartalet, i hvert år det finnes.
            select substr(max(kvartal), 5, 2) as kvartalsnr
            from clean_yrke_kvartal
        ),
        punkter as (
            select
                cast(substr(k.kvartal, 1, 4) as integer) as aar,
                k.kvartal                                as kvartal
            from clean_yrke_kvartal k, anker a
            where substr(k.kvartal, 5, 2) = a.kvartalsnr
            group by 1, 2
        ),
        bestand as (
            select p.aar, p.kvartal, k.yrke, k.lonnstakere
            from clean_yrke_kvartal k
            join punkter p on p.kvartal = k.kvartal
        ),
        kjonn as (
            select
                p.aar,
                k.yrke,
                max(case when k.kjonn = 'kvinner' then k.lonnstakere end) as kvinner,
                max(case when k.kjonn = 'menn'    then k.lonnstakere end) as menn
            from clean_yrke_kjonn_kvartal k
            join punkter p on p.kvartal = k.kvartal
            group by 1, 2
        ),
        trekk as (
            select
                p.aar,
                t.yrke,
                max(case when t.variabel = 'gjsnalder'   then t.verdi end) as gjennomsnittsalder,
                max(case when t.variabel = 'gjavtarbtid' then t.verdi end) as avtalt_arbeidstid
            from clean_yrke_trekk_kvartal t
            join punkter p on p.kvartal = t.kvartal
            group by 1, 2
        ),
        lonn as (
            select
                p.aar,
                l.yrke,
                l.median_lonn_nominell as median_lonn,
                l.median_lonn_realt    as reallonn
            from mart_arbeidsmarked_lonn_kvartal l
            join punkter p on p.kvartal = l.kvartal
        ),
        -- Reserven fra 11418. Bare året trengs — den har ikke kvartaler å
        -- koble på punkter med, og skal uansett bare fylle et hull
        -- kvartalsserien selv lot stå.
        reserve as (
            select yrke, aar, median_lonn_arlig
            from clean_yrke_lonn_aar
        )
        select
            b.yrke                                              as yrke,
            y.navn                                              as yrke_navn,
            substr(b.yrke, 1, 1)                                as hovedgruppe,
            h.navn                                              as hovedgruppe_navn,
            b.aar                                               as aar,
            b.kvartal                                           as kvartal,

            cast(b.lonnstakere as bigint)                       as lonnstakere,
            cast(k.kvinner as bigint)                           as kvinner,
            cast(k.menn as bigint)                              as menn,
            -- nullif på nevneren: 0/0 er NaN, og en NaN sklir gjennom
            -- «is null» og havner i figuren som et hull ingen sjekk fanget.
            k.kvinner / nullif(cast(b.lonnstakere as double), 0) as kvinneandel,

            -- Kildens 0 betyr «ingen å regne over». Se docstringen til
            -- clean.yrke_trekk_kvartal. Mangler kvartalsserien tallet helt,
            -- prøves reserven fra 11418 før feltet blir stående som null —
            -- se moduldocstringen for hvorfor det er trygt bare for nivået,
            -- ikke for reallønna.
            coalesce(nullif(l.median_lonn, 0), r.median_lonn_arlig) as median_lonn,
            nullif(l.reallonn, 0)                               as reallonn,
            nullif(t.gjennomsnittsalder, 0)                     as gjennomsnittsalder,
            nullif(t.avtalt_arbeidstid, 0)                      as avtalt_arbeidstid,

            f.sykefravaer_pst                                   as sykefravaer_pst
        from bestand b
        join clean_styrk y on y.kode = b.yrke and y.nivaa = 4
        join clean_styrk h on h.kode = substr(b.yrke, 1, 1)
        left join kjonn k on k.yrke = b.yrke and k.aar = b.aar
        left join trekk t on t.yrke = b.yrke and t.aar = b.aar
        left join lonn  l on l.yrke = b.yrke and l.aar = b.aar
        left join reserve r on r.yrke = b.yrke and r.aar = b.aar
        left join clean_yrke_sykefravaer f on f.yrke = b.yrke and f.aar = b.aar
        order by b.yrke, b.aar
    """)
