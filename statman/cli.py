"""Kommandolinje. Tynn — all logikk ligger i modulene under."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from statman import catalog as catalog_mod
from statman import io, registry
from statman.sources import ssb, synthetic

app = typer.Typer(add_completion=False, help="Statman — norsk offentlig statistikk.")


def _parse_codes(pairs: list[str] | None) -> dict[str, str]:
    codes: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"Forventet VARIABEL=KODE, fikk {pair!r}")
        codes[key.strip()] = value.strip()
    return codes


@app.command("models")
def list_models() -> None:
    """Vis alle registrerte modeller i byggerekkefølge."""
    registry.discover()
    for name in registry.build_order():
        spec = registry.registry()[name]
        built = "✓" if io.model_path(name).exists() else " "
        deps = ", ".join(spec.deps) or "—"
        typer.echo(f"[{built}] {name:<28} {spec.doc}")
        typer.echo(f"      deps: {deps}")


def _bygg(targets: list[str] | None) -> list[registry.BuildResult]:
    """Bygg, og vis forventede feil som beskjed i stedet for stakksporing.

    Manglende rådata og feilede sjekker er normale utfall man skal kunne
    lese og handle på, ikke krasj.
    """
    try:
        return registry.build(targets)
    except (registry.MissingRawData, registry.CheckFailed) as feil:
        typer.secho(str(feil), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None


@app.command()
def build(
    targets: Annotated[list[str] | None, typer.Argument(help="Modellnavn. Tomt = alt.")] = None,
) -> None:
    """Bygg modeller og alt de avhenger av."""
    for result in _bygg(targets or None):
        typer.echo(f"{result.name:<28} {result.rows:>8} rader  {result.seconds:6.2f}s")


@app.command("ingest-synthetic")
def ingest_synthetic(seed: int = 1) -> None:
    """Generer det syntetiske datasettet og skriv det til rålaget."""
    for dataset, path in synthetic.ingest(seed).items():
        typer.echo(f"{dataset:<16} -> {path}")


@app.command("ingest-ssb")
def ingest_ssb(
    table_id: Annotated[str, typer.Argument(help="Tabell-ID, f.eks. 03013")],
    code: Annotated[
        list[str] | None,
        typer.Option("--code", "-c", help="Filter, f.eks. -c Tid=TOP(12) -c Konsumgrp=TOTAL"),
    ] = None,
    codelist: Annotated[
        list[str] | None,
        typer.Option("--codelist", "-l", help="Kodeliste, f.eks. -l Region=agg_KommSummerHist"),
    ] = None,
    dataset: Annotated[
        str | None,
        typer.Option("--dataset", help="Mappenavn under raw/ssb/. Standard er tabell-ID-en."),
    ] = None,
    metadata: Annotated[bool, typer.Option(help="Hent metadata i stedet for data")] = False,
) -> None:
    """Hent en SSB-tabell og skriv svaret uendret til rålaget."""
    if metadata:
        path = ssb.fetch_metadata(table_id)
    else:
        path = ssb.fetch_table(
            table_id,
            value_codes=_parse_codes(code),
            codelists=_parse_codes(codelist),
            dataset=dataset,
        )
    meta = io.read_meta(path)
    typer.echo(f"{path}\n  {meta['bytes']} bytes, sha256 {meta['sha256'][:12]}…")


@app.command("ssb-probe")
def ssb_probe() -> None:
    """Sjekk hvilken PxWebApi-basis-URL som faktisk svarer."""
    result = ssb.probe()
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["working"]:
        raise typer.Exit(code=1)


@app.command("metrics")
def list_metrics() -> None:
    """Vis metrikkatalogen."""
    for key, m in sorted(catalog_mod.metrics().items()):
        typer.echo(f"{key:<24} {m.label}  [{m.unit}]  -> {m.model}.{m.column}")


@app.command("ssb-codelist")
def ssb_codelist(codelist_id: Annotated[str, typer.Argument(help="F.eks. agg_KommSummerHist")]) -> None:
    """Vis hva en kodeliste inneholder — nyttig før du velger aggregering."""
    doc = ssb.fetch_codelist(codelist_id)
    values = doc.get("values") or []
    typer.echo(f"{doc.get('id')}  {doc.get('label')}  ({doc.get('type')}, {len(values)} verdier)")
    for value in values[:20]:
        kilder = value.get("valueMap") or []
        suffix = f"  <- {', '.join(kilder)}" if len(kilder) > 1 else ""
        typer.echo(f"  {value.get('code'):<10} {value.get('label')}{suffix}")
    if len(values) > 20:
        typer.echo(f"  … og {len(values) - 20} til")


@app.command()
def publish(
    slugs: Annotated[
        list[str] | None,
        typer.Argument(help="Sakspakker i output/. Tomt = alle som er klare."),
    ] = None,
) -> None:
    """Publiser ferdige sakspakker som artikler i docs/.

    Leser `artikkel.json` fra sakspakken og skriver en selvstendig HTML-side
    per sak, pluss arkivsida. Ingenting regnes ut på nytt — tallene er de som
    lå i sakspakken.
    """
    from statman.publish import site

    try:
        written = site.publish_all(slugs or None)
    except (site.PublishError, FileNotFoundError, ValueError) as feil:
        typer.secho(str(feil), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    for path in written:
        typer.echo(str(path))


@app.command("published")
def list_published() -> None:
    """Vis hva som ligger i docs/, og hva som står klart i output/."""
    from statman.publish import site

    for article in site.published():
        dato = article.published or "—"
        typer.echo(f"{dato}  {article.slug:<32} {article.title}")

    ute = {a.slug for a in site.published()}
    klare = [p.name for p in site.packages() if p.name not in ute]
    if klare:
        typer.echo(f"\nKlar til publisering: {', '.join(klare)}")


# Ende-til-ende-eksempler. Hvert modul har `ingest()`, `MODELS` og `main()`.
EXAMPLES: dict[str, str] = {
    "kraftpris": "examples.kraftpris_chart",
    "befolkning": "examples.befolkningsvekst",
    "preben": "examples.preben_borgerlig",
    "preben-trend": "examples.preben_meningsmalinger",
}


@app.command()
def example(
    navn: Annotated[str, typer.Argument(help=f"Ett av: {', '.join(EXAMPLES)}")] = "kraftpris",
) -> None:
    """Kjør et helt eksempel: ingest -> build -> sakspakke i output/."""
    # `examples/` er ikke en installert pakke, bare en mappe i prosjektet.
    # Vi legger prosjektroten på sys.path her i stedet for å pakke den inn.
    import importlib
    import sys

    if navn not in EXAMPLES:
        raise typer.BadParameter(f"Ukjent eksempel {navn!r}. Kjente: {', '.join(EXAMPLES)}")

    root = str(io.project_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    module = importlib.import_module(EXAMPLES[navn])

    module.ingest()
    for result in _bygg(module.MODELS):
        typer.echo(f"{result.name:<32} {result.rows:>8} rader  {result.seconds:6.2f}s")
    for path in module.main():
        typer.echo(str(path))


if __name__ == "__main__":  # pragma: no cover
    app()
