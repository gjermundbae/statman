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
| `output` | Sakspakke: data, graf, notat, artikkelspesifikasjon | filer | forbeholdene følger tallene ut |
| `publish` | Artikkel: én selvstendig side, og arkivet | HTML | ingenting regnes ut her |

`raw → clean` er mekanisk. `clean → mart` er der valgene tas. `catalog` er der
det står hvorfor. Analysen leser fra `mart` og skriver til `output` — den går
aldri direkte i `raw`, bortsett fra for å lese proveniens. `publish` leser bare
fra `output`.

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

## Publisering

Publiseringslaget har én regel, og den er streng: **det teller ikke, summerer
ikke, og velger ikke utvalg.** Alle tall kommer inn ferdig formatert, alle
forbehold kommer fra katalogen. En renderer som ikke kan regne, kan heller ikke
regne feil — og da er det trygt å la den være leken.

Regelen sto opprinnelig som «det regner ingenting ut», og ble skjerpet til det
den egentlig betyr da figurene begynte å tegnes i sida. En figur må mappe verdi
til piksel et sted, og den skaleringen er ombrekking — samme slag som at
rendereren allerede bestemmer kolonnebredder. Den sier ingenting om verden.

Grensa er verdt å tegne skarpt, for begge sidene av den er lette å bomme på. Da
figurlaget ble prototypet, lot vi sida gjøre to ting den ikke skulle:

- **Aggregere.** Fylkestall summert opp fra kommune-CSV-en ga Vestfold +8,5 %
  der artikkelen sa +14,1 %, fordi tre kommuner er holdt utenfor som ikke
  sammenlignbare. Utvalget er et valg, og valg hører i analysen.
- **Telle.** «Hvor mange kommuner vokste» talt i nettleseren ga 205 av 323. Det
  riktige er 203, pluss én som endte på nøyaktig null. Sida talte på de
  *avrundede* prosentene, og to kommuner på ±0,04 % havnet på feil side.

Begge tallene så helt rimelige ut. Det er hele poenget: en renderer som regner
gir ikke feilmelding, den gir et annet tall.

Seamen er en fil. Når en analyse er ferdig, skriver den en `Article` — tittel,
ingress, seksjoner, figurer, tabeller med ferdige celler, metrikknøklene
forbeholdene skal hentes fra, og proveniensen fra byggeloggen — ned som
`artikkel.json` i sakspakken. `statman publish` leser den derfra. Det er derfor
publisering ikke trenger å importere analysen som lagde tallene, og derfor en
notebook kan publiseres på nøyaktig samme måte som et eksempel.

Notatet i sakspakken rendres fra den samme `Article`. Det er samme grep som at
forbehold hentes fra katalogen framfor å skrives på nytt, løftet ett nivå opp:
`notat.md` og den publiserte sida er ikke to tekster som ligner, de er én tekst
i to former.

Publisering er sin egen kommando, ikke et steg i `example`. Det å være fornøyd
med et resultat er en vurdering, og vurderinger hører ikke hjemme i en pipeline.

Sida er ett dokument. CSS og JS ligger inne i fila, det finnes ingen fonter,
biblioteker eller sporing utenfra, og en sjekk stopper publiseringen om noe
skulle bli hentet over nettet likevel. Det gjør at sida virker fra disk, at den
kan arkiveres som én fil, og at den ikke råtner når et CDN legges ned.

## Figurene

En `Chart` er en figur sida tegner selv, som SVG. Den bærer merkene med de
tallene analysen valgte, ferdig formatert, og **ingen farger** — analysen sier
at et merke er «vekst», publiseringslaget bestemmer hvilken grønn det blir.
Paletten kan dermed byttes ett sted når den ikke består fargeblindhetssjekken,
uten å røre en eneste analyse.

Hver figur har en PNG under seg. Den står i notatet, den står i sida for en
leser uten JavaScript, og den settes inn igjen om tegningen skulle ryke. En
figur er altså aldri *avhengig* av å være interaktiv; interaktiviteten er noe
som kommer i tillegg. PNG-en ligger i `<noscript>`, så den som får SVG-en aldri
laster den ned.

Egen SVG framfor et diagrambibliotek er den samme avveiningen som at
byggegrafen er egen kode: Plotly er 3,5 megabyte og forutsetter et CDN, og
begge deler bryter regelen om én selvstendig fil. Figurene arver sidas
CSS-variabler, så mørk modus og typografi bare virker.

Interaktivitet legges til der leseren er en av radene. Kommunesaken har 323
kommuner med hvert sitt navn; en leser fra Ibestad skal kunne finne Ibestad.
En figur som viser en *fordeling* og ikke identiteter — spaghettiplottene —
har lite å hente på å bli klikkbar, og blir stående som PNG.

Arkivet bygges av det som ligger i `docs/`, ikke av det som ligger i `output/`.
`output/` er gitignorert og tomt i en fersk klone; `docs/` er det som faktisk er
publisert. Mappa heter `docs/` fordi GitHub Pages kan servere nettopp den fra
hovedgrenen uten workflow og uten byggesteg — ingen server, ingen orkestrator,
også her.

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
- ~~**Nettside / arkiv.**~~ *Bygget, ett hakk før den opprinnelige terskelen på
  tre sakspakker.* Grunnen til å ta det nå og ikke etterpå: formen på en
  sakspakke bestemmes av den som skriver den, og seamen mot publisering måtte
  finnes **før** sakspakke nummer tre, ikke etter. Arkivet er en liste. Blir
  det mange nok saker til at en liste ikke holder, er søk og emneknagger neste.
- **Nyhetsbrev.** Fortsatt utsatt. Krever at noen abonnerer.
- ~~**Figurer som SVG.**~~ *Gjort, men ikke slik det sto her.* Terskelen var at
  en figur skulle se dårlig ut på skjerm. Det som faktisk utløste det var noe
  annet: en leser kunne ikke finne sin egen kommune blant 323 prikker. SVG ble
  midlet, ikke målet — se «Figurene» over.
- **Linjediagram i `Chart`.** Punkt, stripe og søyle finnes. Linja låser opp
  rente_bolig og begge preben-sakene på én gang, og bygges når den første av
  dem skal røres.
- **Figurtypografi på små skjermer.** En fast `viewBox` skalerer teksten ned
  med bredden, så aksemerkene blir små under ~500 piksler. Løsningen er kjent —
  eget utsnitt og færre merker under et brytepunkt — og gjøres når noen leser
  en av sakene på telefon og blir irritert.
- **Tastaturnavigasjon i punktskyer.** Søylene kan fokuseres, nedtrekket virker,
  og tabellen har tallene. Å tabbe mellom 323 prikker er derimot ikke løst, og
  krever noe smartere enn `tabindex` på hver av dem.
- **Objektlagring og backup for rådata.** `data/` er gitignorert, så rådata,
  byggelogger og sakspakker finnes i dag bare på maskinen de ble laget på.
  Rådata er reproduserbart via konnektorene, men ikke bit for bit hvis kilden
  har revidert tall i mellomtiden.

## Stack

Python 3.12 · DuckDB · Polars · httpx · Typer · PyYAML · uv
Grafer: matplotlib for arbeid og for fallback, egen SVG for publisering.
