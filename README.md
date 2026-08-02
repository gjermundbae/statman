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
catalog/metrics.yml      definisjoner, enheter, forbehold
examples/                ende-til-ende-eksempler
tests/
data/                    gitignorert: raw/ clean/ mart/ + byggelogger
output/                  gitignorert: sakspakker
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

## Analyse

```python
import statman as sm
from statman import io

df = sm.load("mart.befolkningsvekst")   # -> polars.DataFrame
m = sm.metric("folkevekst_pst")
print(m.note())                          # definisjon + forbehold

io.read_manifest("mart.befolkningsvekst")["raw"]   # hvilken henting ga tallene
```

## Å legge til en kilde

1. `statman/sources/<kilde>.py` med en `fetch`-funksjon som skriver via
   `io.write_raw` og aldri tolker innholdet.
2. En `clean.<navn>`-modell som typer og normaliserer. For json-stat2 gjør
   `jsonstat.to_frame` utbrettingen; modellen gjør resten i SQL.
3. Sjekker på modellen. To til fire, og hver av dem skal kunne feile.
4. En rad i `catalog/metrics.yml` — særlig `caveats` og `breaks`.

Modellkontrakten i sin helhet står i docstringen til `statman/registry.py`.

## SSB-endepunktet

SSB har flyttet PxWebApi 2.0 mellom `/v2` og `/v2-beta` i overgangen fra
PxWeb 1. Konnektoren prøver `/v2` først og faller tilbake til `/v2-beta`.
Kjør `statman ssb-probe` hvis noe ser rart ut — den skiller nettverksfeil fra
flyttet endepunkt. Overstyr med `STATMAN_SSB_BASE` ved behov.
