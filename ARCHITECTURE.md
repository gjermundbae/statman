# Statman — arkitektur

Plattform for å hente, koble og publisere norsk offentlig statistikk.
Python hele veien. Filsystemet er databasen. Ingen server, ingen orkestrator.

Dette dokumentet forklarer *hvorfor* systemet ser ut som det gjør. Hvordan det
brukes står i [README.md](README.md); hva grensesnittene garanterer står i
docstringene, nærmest koden det gjelder.

## Prinsipper

1. **Rådata er uforanderlig.** Et API-svar skrives aldri over. Hver henting er
   en ny tidsstemplet mappe. Endrer en kilde et tall i ettertid, finnes begge
   versjonene og differansen kan sees.
2. **Transformasjoner er Python-funksjoner.** SQL brukes inni dem der SQL er
   best, men grensesnittet er Python.
3. **Alt materialiseres til Parquet.** DuckDB er motoren, filsystemet er
   lageret.
4. **Ingenting lander før det er kontrollert.** En modell som bryter sine egne
   sjekker etterlater seg ingen fil.
5. **Proveniens følger tallene.** Fra råfilas kvittering, gjennom byggeloggen,
   til forbeholdene i sakspakken. Et publisert tall skal kunne spores tilbake
   til hentingen som ga det.
6. **Utsett alt som ikke trengs for neste analyse.** Listen over utsatte ting
   står nederst — den er en del av designet, ikke en mangel.

## Lag

Lagene skiller seg ikke på hvem som lager dem, men på hva slags påstand de
gjør — og dermed på hva som ikke får skje i dem.

| Lag | Innhold | Format | Regelen som gjelder der |
|---|---|---|---|
| `raw` | Kildesvaret uendret, med kvittering | som mottatt | tolkes aldri, filtreres aldri, skrives aldri over |
| `clean` | Én kilde, typet, normaliserte navn, lang form | Parquet | ingen valg — krever noe en vurdering, hører det i mart |
| `mart` | Analyseklare tabeller, koblet på tvers | Parquet | hvert valg begrunnes der det tas |
| `catalog` | Definisjon, enhet, kilde, forbehold, seriebrudd | YAML | ingen tall som kan telles |
| `output` | Sakspakke: data, graf, notat | filer | forbeholdene følger tallene ut |

`raw → clean` er mekanisk. `clean → mart` er der valgene tas. `catalog` er der
det står hvorfor. Analysen leser fra `mart` og skriver til `output` — den går
aldri direkte i `raw`, bortsett fra for å lese proveniens.

Skillet mellom `clean` og `mart` er det som bærer mest. Når en transformasjon
er vanskelig å plassere, er spørsmålet om den kunne vært gjort annerledes av en
fornuftig person. Kunne den det, er den et valg og hører i `mart`.

## Byggegrafen

En modell erklærer hva den trenger, ikke når den skal kjøre. Avhengigheter til
andre modeller gir en topologisk rekkefølge med sykeldeteksjon; avhengigheter
til rådata (`raw:`-prefiks) er inndata og kontrolleres før noe kjøres, slik at
et bygg uten data stopper med en samlet liste i stedet for å feile halvveis.

Sjekker er ikke dokumentasjon, de er en port. De kjøres mot resultatet før det
får sitt endelige navn, så en feilet sjekk etterlater ingenting og lar en
tidligere gyldig tabell stå urørt. To til fire sjekker per modell er nok, og en
sjekk som ikke kan feile er ikke verdt linja.

Dette er egen kode framfor dbt eller en orkestrator fordi det er lite nok til å
leses på en kaffepause. Blir grafen stor nok til at det gjør vondt, ligger
`@model` nær nok dbt til at en migrering er mekanisk.

## Proveniens

Rålaget bærer sin egen kvittering: hva som ble spurt om, hva som kom tilbake,
når, og en sjekksum. Men den stopper der om ingen fører den videre, og et
publisert tall er ikke etterprøvbart før spørsmålet «hvilken henting ga dette»
kan besvares fra disk.

Derfor skriver kjøreren en byggelogg ved siden av hver tabell: når den ble
bygget, hvilke sjekker som passerte, og hvilken *oppløst* råversjon den hviler
på — ikke «den nyeste», som kan ha blitt en annen siden. Råversjonene arves
oppstrøms, så en mart-tabell kan spores til kilden uten å følge kjeden manuelt.

Publisering leser proveniens herfra. Ingest, bygg og sakspakke kjører gjerne i
samme kommando, og uten byggeloggen kan et notat oppgi en henting som ikke ga
tallene ved siden av.

## Det semantiske laget

Én fil. Formålet er å hindre at det som forklarer et tall forsvinner tre uker
etter at tallet ble laget.

En metrikk peker på en modell og en kolonne, og bærer enhet, kilde, `caveats`
og `breaks`. De to siste er de som betyr noe — de er forskjellen på en
tallpakke som lar seg forsvare og en som ikke gjør det. Et hjelpekall gir
serien *sammen med* forbeholdene, så de følger med inn i analysen og videre ut
i sakspakken i stedet for å bli skrevet på nytt hver gang.

Forbehold skrives for hånd, fordi de er vurderinger. Nettopp derfor hører
opptalte tall ikke hjemme der: «negativt i de fleste kommuner» er et varig
forbehold, «negativt i 200 av 323» er et funn som regnes ut i sakspakken og
forvitrer i katalogen.

## Bevisst utsatt

Reservert, ikke glemt. Hver av dem bygges når en konkret analyse krever det:

- ~~**Kommune-crosswalk.**~~ *Delvis løst, og billigere enn antatt.* Trengtes
  over femten år med to kommunereformer, men ikke som dimensjonstabell med
  gyldighetsperioder: kildens egne aggregerte kodelister reverserer
  sammenslåingene, og delinger og grensejusteringer kan leses ut av tallene,
  siden endringen i bestanden ikke er lik den rapporterte strømmen når grensene
  har flyttet seg. En ekte dimensjonstabell er fortsatt utsatt, til noe krever
  å koble to *ulike* kilder på kommunenummer.
- **Tids- og næringskodedimensjoner.** Samme regel.
- **Deflatering som delt funksjon.** Etter andre gang den er skrevet for hånd.
- **Inkrementell bygging.** Når full rebuild ikke lenger går på sekunder.
- **Avviksmonitor.** Krever ingest på skjema, altså automatisering først.
- **Scheduling.** Når manuell kjøring blir irriterende, ikke før.
- **Nettside / arkiv / nyhetsbrev.** Etter tre sakspakker.
- **Objektlagring og backup for rådata.** `data/` er gitignorert, så rådata,
  byggelogger og sakspakker finnes i dag bare på maskinen de ble laget på.
  Rådata er reproduserbart via konnektorene, men ikke bit for bit hvis kilden
  har revidert tall i mellomtiden.

## Stack

Python 3.12 · DuckDB · Polars · httpx · Typer · PyYAML · uv
Grafer: matplotlib for arbeid, Datawrapper for publisering.
