# Statman

Plattform for å hente, koble og publisere norsk offentlig statistikk.
Se [ARCHITECTURE.md](ARCHITECTURE.md) for hvorfor den ser ut som den gjør.

## Kom i gang

```bash
uv sync                           # installerer avhengigheter og pakka editable
uv run statman example kraftpris  # syntetisk kjede, uten nettverk -> output/
uv run statman example befolkning # ekte SSB-tall -> output/
uv run pytest                     # alt unntatt nettverkstestene
uv run pytest -m network          # tester som faktisk snakker med SSB
```

`uv sync` installerer prosjektet editable. Derfor er **alle imports absolutte**
(`from statman.registry import model`) og ingenting trenger `sys.path`-triksing.
Skript utenfor pakka fungerer også, siden `pyproject.toml` setter
`pythonpath = ["."]` for pytest.

## Kommandoer

| Kommando | Gjør |
|---|---|
| `statman models` | modeller i byggerekkefølge, med hake for bygget |
| `statman build [navn ...]` | bygger modeller og alt oppstrøms |
| `statman metrics` | viser metrikkatalogen |
| `statman example [navn]` | ingest → build → sakspakke i `output/` |
| `statman publish [slug ...]` | sakspakke → artikkel i `docs/`. Tomt = alle klare |
| `statman published` | hva som er publisert, og hva som står klart |
| `statman ingest-synthetic` | genererer det syntetiske datasettet |
| `statman ingest-ssb 03013 -c Tid=TOP(12)` | henter en SSB-tabell |
| `statman ingest-ssb 06913 -l Region=agg_KommSummerHist --dataset 06913_kommune` | samme, med aggregert kodeliste |
| `statman ssb-probe` | sjekker hvilken PxWebApi-basis-URL som svarer |
| `statman ssb-codelist <id>` | viser hva en kodeliste faktisk aggregerer |

`statman build` uten argumenter bygger alt, og krever da rådata fra alle
kilder. Til vanlig navngis målet: `statman build mart.<tabell>`. Mangler
rådata, sier bygget fra om hvilke datasett det gjelder før noe kjøres.

## Struktur

```
statman/
  io.py                  stier, proveniens, byggelogg, materialisering
  registry.py            @model, byggegraf, sjekker — modellkontrakten
  catalog.py             det semantiske laget
  jsonstat.py            json-stat2 -> lang tabell
  http.py                rate limiting
  cli.py
  sources/               én modul per kilde: hent, skriv ned uendret
  models/                transformasjonene
  publish/               sakspakke -> artikkel: Article, markdown, html, site
  publish/assets/        statman.css/js (sida), graf.css/js (figurene)
catalog/metrics.yml      definisjoner, enheter, forbehold
examples/                ende-til-ende-eksempler
tests/
data/                    gitignorert: raw/ clean/ mart/ + byggelogger
output/                  gitignorert: sakspakker
docs/                    publiserte artikler — det eneste genererte som er i git
```

## Eksemplene

Begge går hele veien fra API-kall til en sakspakke i `output/` — data, grafer
og et notat der funn, metode og forbehold står sammen, og der forbeholdene er
hentet fra katalogen framfor skrevet på nytt.

**`kraftpris`** kjører uten nettverk mot en syntetisk kilde. Dataene er
oppdiktet, men problemet er ekte: nominelle kroner fra ulike år kan ikke
sammenlignes uten å deflateres.

**`befolkning`** henter folkemengde og befolkningsendringer for alle norske
kommuner fra SSB. Det tunge der er ikke prosentregningen, men
kommuneinndelingen — femten år dekker to kommunereformer, en kommunedeling og
et titalls grensejusteringer. Begrunnelsen for hvordan det håndteres står i
`statman/models/mart_befolkning.py`, ikke her.

**`arbeidsmarked`** kobler SSBs yrkesstatistikk og konsumprisindeksen til 407
yrker i STYRK-08, og tegner dem som et flisediagram med sju fargelag — det siste
er reallønnsutvikling. Det tunge der er å vite hvilke yrker som *ikke* tåler en
tiårsserie: en omkoding i Forsvaret ser ut som 365 prosent vekst, «Uoppgitt» er
ikke et yrke, og SSB merker selv et brudd i yrkesrapporteringen midt i perioden.
Se `statman/models/mart_arbeidsmarked.py`.

## Analyse

```python
import statman as sm
from statman import io

df = sm.load("mart.befolkningsvekst")   # -> polars.DataFrame
m = sm.metric("folkevekst_pst")
print(m.note())                          # definisjon + forbehold

io.read_manifest("mart.befolkningsvekst")["raw"]   # hvilken henting ga tallene
```

## Publisering

En sakspakke i `output/` er arbeidsformen. Når du er fornøyd med den, blir den
en artikkel:

```bash
statman publish befolkningsvekst_kommune
```

Det skriver `docs/<slug>/index.html` — én selvstendig side med grafene,
tabellene, metoden, forbeholdene og en kvittering nederst som sporer tallene
tilbake til hentingen som ga dem — og bygger arkivsida `docs/index.html` på
nytt. Ingenting regnes ut på veien; tallene er de som lå i sakspakken.

Slå på GitHub Pages én gang: *Settings → Pages → Deploy from a branch →
`master` / `docs`*. Etter det er publisering en `git push`.

`docs/CNAME` holder det egne domenet. `statman publish` skriver bare
`index.html`, `.nojekyll` og én mappe per sak, og sletter aldri noe i `docs/` —
så fila blir stående. Forsvinner den, faller sida tilbake til
`gjermundbae.github.io/statman`.

Se sida lokalt før du pusher:

```bash
python -m http.server 8765 --directory docs
```

### Å publisere en analyse som ikke er et eksempel

`statman publish` leser `artikkel.json` fra sakspakken og importerer aldri
koden som lagde tallene. En notebook som skriver fila kan publiseres likt:

```python
from statman import io, publish

art = publish.Article(
    slug="min_sak",
    kicker="Kraftpris · SSB tabell 09364",
    title="…",
    lead="…",
    published="2026-08-03",
    sections=(
        publish.Section("Funn", (
            publish.Stats((publish.Stat("+14,4 %", "Vekst", "over perioden"),)),
            publish.Findings(("Et **funn**.",)),
            publish.Figure("graf.png", alt="…", caption="…", width="full"),
        )),
    ),
    caveats=("folkevekst_pst",),        # nøkler inn i catalog/metrics.yml
    provenance={"Hentet": "…", "sha256": "…"},
    files=(("data.csv", "alle rader"),),
)

pakke = io.output_dir() / art.slug
art.validate(pakke)                      # feiler på ukjent forbehold, manglende figur
publish.markdown.write(art, pakke / "notat.md")
art.write(pakke)
```

Forbehold oppgis som *nøkler*, aldri som tekst. Skriver du dem av for hånd, har
du laget en kopi som forvitrer — og `validate()` sier fra hvis nøkkelen ikke
finnes.

### Figurer sida tegner selv

`publish.Figure` er en PNG. `publish.Chart` er en figur sida tegner som SVG, med
en PNG under seg for den som ikke har JavaScript:

```python
publish.Chart(
    kind="scatter",                     # scatter · strip · bars · treemap · line
    marks=(
        publish.Mark(
            label="Ibestad", group="Troms",
            x=-161.9, y=69.2, size=0.05, tone="fall",
            values=(publish.Readout("Vekst", "-9,3 %", "fall"),),
        ),
    ),
    fallback="komponenter.png",         # står i notatet, og i sida uten skript
    alt="…",
    x=publish.Axis("Fødselsoverskudd →", lo=-177, hi=152,
                   ticks=(-150, 0, 150), tick_labels=("-150", "0", "150")),
    y=publish.Axis("← Nettoinnflytting", lo=-160, hi=485),
    legend=(("vekst", "Kommunen vokste"), ("fall", "Kommunen falt")),
    link="kommune", picker="Framhev kommune", group_label="Avgrens til fylke",
)
```

Figurer med samme `link` deler markering: velger leseren en kommune, lyser den
opp i alle sammen. Nøyaktig én av dem setter `picker`.

`tone` er en *fargerolle* — `vekst`, `fall`, `kat1`…`kat4`, `noytral` — ikke en
farge. Hvilken grønn «vekst» blir står i `publish/assets/graf.css`, sammen med
målingene som viser at den kan skilles fra `fall` av en leser som ikke ser rødt.
En ukjent rolle stopper publiseringen.

Ved siden av de kategoriske rollene finnes to *ordnede* skalaer, der rekkefølgen
bærer mening: `skala1`…`skala5` stiger, `avvik1`…`avvik5` divergerer om en midte,
og `mangler` er ikke en verdi, men fraværet av en. Hvilket trinn en verdi havner
på er en inndeling, altså et valg, og gjøres i analysen.

### Flisediagram med flere fargelag

`kind="treemap"` deler flaten etter `size` og grupperer på `group`. Den kan
farges på flere måter samtidig, én `Layer` per måte:

```python
publish.Chart(
    kind="treemap",
    layers=(
        publish.Layer("lonn", "Median månedslønn",
                      legend=(("skala1", "under 40 000 kr"),
                              ("skala5", "75 000 kr og over"))),
        publish.Layer("vekst", "Endring på 10 år",
                      legend=(("avvik1", "ned over 20 %"),
                              ("avvik5", "opp over 25 %"))),
    ),
    layer_label="Farg flisene etter",
    marks=(
        publish.Mark(label="Sykepleiere", group="Akademiske yrker",
                     size=59306, tones=("skala5", "avvik4")),
    ),
    fallback="fliser.png", alt="…",
)
```

`tones` er én rolle per lag, i lagenes rekkefølge — ett merke som mangler en av
dem stopper publiseringen, for det ville blitt usynlig i nøyaktig ett lag.
Oppdelingen regnes ut i sida (squarified treemap); analysen sier bare hvor stor
en flate er. PNG-en under kan bare vise ett av lagene, og det skal stå i
bildeteksten hvilket.

### Linjediagram

`kind="line"` tegner én linje per merke. Merket bærer da en *serie* framfor ett
punkt:

```python
publish.Mark(
    label="Alle yrker", tone="kat1", pin=True,
    points=((0, 100.0), (4, 104.5), (7, 100.3), (10, 105.3)),
    point_labels=("2016K2 · 100,0", "2020K2 · 104,5",
                  "2023K2 · 100,3", "2026K2 · 105,3"),
    values=(publish.Readout("Reallønn", "+5,3 %", "vekst"),),
)
```

`point_labels` er det boblen viser for punktet leseren peker på, ferdig
formatert; `values` er merkets faste avlesninger under. `pin` gir linja navn
der den slutter og tegner den tykkere — bruk den på den ene serien som er
målestokken. Punktene tegnes slik de kom: ingen utjevning, og et hull blir et
hull framfor en rett strekning.

Alt annet gjelder som før: tallene kommer ferdig formatert, og sida verken
teller, summerer eller velger utvalg. Den regner bare ut hvor på skjermen et
merke skal stå.

## Å legge til en kilde

1. `statman/sources/<kilde>.py` med en `fetch`-funksjon som skriver via
   `io.write_raw` og aldri tolker innholdet.
2. En `clean.<navn>`-modell som typer og normaliserer. For json-stat2 gjør
   `jsonstat.to_frame` utbrettingen; modellen gjør resten i SQL.
3. Sjekker på modellen. To til fire, og hver av dem skal kunne feile. Ta med
   `min_rows:1` — de andre formene teller *rader som bryter*, og en tom tabell
   har ingen. Uten den lander en modell som lager ingenting like stille som en
   riktig.
4. En rad i `catalog/metrics.yml` — særlig `caveats` og `breaks`.

Modellkontrakten i sin helhet står i docstringen til `statman/registry.py`.

## SSB-endepunktet

SSB har flyttet PxWebApi 2.0 mellom `/v2` og `/v2-beta` i overgangen fra
PxWeb 1. Konnektoren prøver `/v2` først og faller tilbake til `/v2-beta`.
Kjør `statman ssb-probe` hvis noe ser rart ut — den skiller nettverksfeil fra
flyttet endepunkt. Overstyr med `STATMAN_SSB_BASE` ved behov.
