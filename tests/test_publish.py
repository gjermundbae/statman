"""Publiseringslaget.

Sjekkene her er de samme fire spørsmålene som stilles ellers i prosjektet:
kommer teksten fra ett sted, følger proveniensen med, kan noe lande uten å
være kontrollert, og kan resultatet endre seg uten at inndataene gjorde det.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from statman import io
from statman.publish import html, markdown, site
from statman.publish.article import (
    Article,
    Axis,
    Chart,
    Figure,
    Findings,
    Guide,
    Mark,
    Prose,
    Readout,
    Section,
    Stat,
    Stats,
    Table,
)

KATALOG = """
testmetrikk:
  label: Testmetrikk
  model: mart.test
  column: verdi
  unit: personer
  source: Oppdiktet
  caveats:
    - Et forbehold som må følge tallet.
  breaks:
    - Serien er brutt i 2020.
"""


@pytest.fixture
def katalog(project: Path) -> Path:
    path = io.catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(KATALOG, encoding="utf-8")
    return path


def lag_graf(**endringer) -> Chart:
    grunn = dict(
        kind="scatter",
        marks=(
            Mark(
                label="Oslo",
                group="Oslo",
                x=1.0,
                y=2.0,
                size=1.0,
                tone="vekst",
                values=(Readout("Vekst", "+21,6 %", "vekst"),),
                pin=True,
            ),
            Mark(label="Røst", group="Nordland", x=-1.0, y=-2.0, size=0.1, tone="fall"),
        ),
        fallback="graf.png",
        alt="Et punktdiagram",
        x=Axis("Fødsler", -3.0, 3.0, (-3.0, 0.0, 3.0), ("−3", "0", "3")),
        y=Axis("Flytting", -3.0, 3.0, (-3.0, 0.0, 3.0), ("−3", "0", "3")),
        legend=(("vekst", "Vokste"), ("fall", "Falt")),
        guides=(Guide("diagonal", 0.0, ("nullvekst",)),),
        caption="Bildetekst",
        source="Kilde: X",
    )
    grunn.update(endringer)
    return Chart(**grunn)  # type: ignore[arg-type]


def lag_artikkel(**endringer) -> Article:
    grunn = dict(
        slug="testsak",
        kicker="Test · kilde",
        title="En testsak",
        lead="Ingressen står her.",
        published="2026-08-03",
        sections=(
            Section(
                "Funn",
                (
                    Stats((Stat("+14,4 %", "Vekst", "over perioden"),)),
                    Findings(("Et **funn** med `kode` og *trykk*.",)),
                    Prose("Et avsnitt."),
                    Figure("graf.png", alt="En graf", caption="Bildetekst", source="Kilde: X"),
                    Table(
                        columns=("Fylke", "Vekst"),
                        rows=(("Oslo", "+21,6 %"), ("Finnmark", "+2,5 %")),
                        align=("left", "right"),
                        caption="Klikk for å sortere.",
                    ),
                ),
            ),
        ),
        caveats=("testmetrikk",),
        provenance={"Kilde": "SSB tabell 06913", "sha256": "abc123"},
        files=(("data.csv", "alle rader"),),
    )
    grunn.update(endringer)
    return Article(**grunn)  # type: ignore[arg-type]


def lag_pakke(root: Path, article: Article) -> Path:
    pakke = io.output_dir() / article.slug
    pakke.mkdir(parents=True, exist_ok=True)
    for navn in article.assets():
        (pakke / navn).write_bytes(b"ikke en ekte fil, men den finnes")
    article.write(pakke)
    return pakke


# --------------------------------------------------------------------------
# Modellen
# --------------------------------------------------------------------------
def test_artikkel_overlever_json(project: Path) -> None:
    """Seamen mot publisering er en fil. Da må den bære alt."""
    original = lag_artikkel()
    pakke = io.output_dir() / "testsak"
    pakke.mkdir(parents=True)
    original.write(pakke)

    assert Article.read(pakke) == original


def test_ukjent_skjema_avvises(project: Path) -> None:
    pakke = io.output_dir() / "testsak"
    pakke.mkdir(parents=True)
    (pakke / "artikkel.json").write_text('{"schema": "noe/annet"}', encoding="utf-8")

    with pytest.raises(ValueError, match="skjema"):
        Article.read(pakke)


# --------------------------------------------------------------------------
# Sjekkene — hver av dem skal kunne feile
# --------------------------------------------------------------------------
def test_forbehold_utenfor_katalogen_stopper(katalog: Path) -> None:
    """Et forbehold er en nøkkel inn i katalogen, ikke en tekst man skriver."""
    with pytest.raises(ValueError, match="finnes ikke i katalogen"):
        lag_artikkel(caveats=("finnes_ikke",)).validate()


def test_figur_som_ikke_ligger_i_pakken_stopper(katalog: Path, tmp_path: Path) -> None:
    tom = tmp_path / "tom"
    tom.mkdir()
    with pytest.raises(ValueError, match="graf.png"):
        lag_artikkel().validate(tom)


def test_tabell_med_feil_radbredde_stopper(katalog: Path) -> None:
    skjev = Table(columns=("A", "B"), rows=(("bare én",),))
    with pytest.raises(ValueError, match="celler"):
        lag_artikkel(sections=(Section("Funn", (skjev,)),)).validate()


def test_slug_må_kunne_stå_i_en_url(katalog: Path) -> None:
    with pytest.raises(ValueError, match="slug"):
        lag_artikkel(slug="Test Sak").validate()


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def test_markdown_henter_forbehold_fra_katalogen(katalog: Path) -> None:
    tekst = markdown.render(lag_artikkel())

    assert "# En testsak" in tekst
    assert "| Fylke | Vekst |" in tekst
    assert "|---|--:|" in tekst
    assert "Et forbehold som må følge tallet." in tekst
    assert "Seriebrudd: Serien er brutt i 2020." in tekst
    assert "sha256" in tekst  # kvitteringen følger med


def test_html_laster_ingenting_over_nettet(katalog: Path) -> None:
    """Sida skal virke fra disk, uten nett, uten CDN."""
    assert html.external_assets(html.render(lag_artikkel())) == []


def test_html_er_deterministisk(katalog: Path) -> None:
    """Samme artikkel gir samme fil. Ellers støyer git ved hver publisering."""
    art = lag_artikkel()
    assert html.render(art) == html.render(art)


def test_html_escaper_tekst(katalog: Path) -> None:
    art = lag_artikkel(sections=(Section("Funn", (Prose("<script>alert(1)</script>"),)),))
    markup = html.render(art)

    assert "<script>alert(1)</script>" not in markup
    assert "&lt;script&gt;" in markup


def test_html_tolker_utheving(katalog: Path) -> None:
    markup = html.render(lag_artikkel())

    assert "<strong>funn</strong>" in markup
    assert "<code>kode</code>" in markup
    assert "<em>trykk</em>" in markup


def test_html_gir_tabellen_justering_og_sortering(katalog: Path) -> None:
    markup = html.render(lag_artikkel())

    assert "data-sorterbar" in markup
    assert '<td class="right">+21,6 %</td>' in markup


# --------------------------------------------------------------------------
# Figurer som tegnes i sida
# --------------------------------------------------------------------------
def test_graf_overlever_json(project: Path) -> None:
    """Figuren er nøstet dypere enn de andre blokkene. Da må rundturen sjekkes."""
    art = lag_artikkel(sections=(Section("Funn", (lag_graf(),)),))
    pakke = io.output_dir() / "testsak"
    pakke.mkdir(parents=True)
    art.write(pakke)

    assert Article.read(pakke) == art


def test_grafen_krever_sin_png(katalog: Path, tmp_path: Path) -> None:
    """Fallbacken er ikke pynt — den er figuren for en leser uten skript."""
    tom = tmp_path / "tom"
    tom.mkdir()
    art = lag_artikkel(sections=(Section("Funn", (lag_graf(),)),))

    assert "graf.png" in art.assets()
    with pytest.raises(ValueError, match="graf.png"):
        art.validate(tom)


def test_ukjent_fargerolle_stopper(katalog: Path) -> None:
    """Fargeroller er et lukket vokabular; en ukjent blir usynlig i sida."""
    skjev = lag_graf(marks=(Mark(label="Oslo", tone="knallrosa"),))
    with pytest.raises(ValueError, match="knallrosa"):
        lag_artikkel(sections=(Section("Funn", (skjev,)),)).validate()


def test_akse_med_feil_antall_merketekster_stopper(katalog: Path) -> None:
    skjev = lag_graf(x=Axis("Fødsler", -3.0, 3.0, (-3.0, 0.0, 3.0), ("−3", "0")))
    with pytest.raises(ValueError, match="merketekster"):
        lag_artikkel(sections=(Section("Funn", (skjev,)),)).validate()


def test_punktdiagram_uten_akser_stopper(katalog: Path) -> None:
    with pytest.raises(ValueError, match="trenger begge akser"):
        lag_artikkel(sections=(Section("Funn", (lag_graf(y=None),)),)).validate()


def test_soyler_uten_segmenter_stopper(katalog: Path) -> None:
    skjev = lag_graf(kind="bars", marks=(Mark(label="Oslo", tone="kat1"),))
    with pytest.raises(ValueError, match="uten segmenter"):
        lag_artikkel(sections=(Section("Funn", (skjev,)),)).validate()


def test_markeringsgruppe_uten_velger_stopper(katalog: Path) -> None:
    """To koblede figurer, ingen som eier nedtrekket: ingenting kan velges."""
    a = lag_graf(link="kommune")
    b = lag_graf(link="kommune")
    with pytest.raises(ValueError, match="nøyaktig én"):
        lag_artikkel(sections=(Section("Funn", (a, b)),)).validate()


def test_to_velgere_i_samme_gruppe_stopper(katalog: Path) -> None:
    a = lag_graf(link="kommune", picker="Velg")
    b = lag_graf(link="kommune", picker="Velg")
    with pytest.raises(ValueError, match="nøyaktig én"):
        lag_artikkel(sections=(Section("Funn", (a, b)),)).validate()


def test_notatet_viser_grafen_som_png(katalog: Path) -> None:
    """Notatet er arbeidsformen og leses i en editor. Der er PNG-en figuren."""
    tekst = markdown.render(lag_artikkel(sections=(Section("Funn", (lag_graf(),)),)))

    assert "![Et punktdiagram](graf.png)" in tekst


def test_grafen_laster_ingenting_over_nettet(katalog: Path) -> None:
    art = lag_artikkel(sections=(Section("Funn", (lag_graf(),)),))
    assert html.external_assets(html.render(art)) == []


def test_grafen_tar_med_figurlaget_bare_når_det_trengs(katalog: Path) -> None:
    """En sak uten figurer skal ikke bære med seg figurmotoren."""
    uten = html.render(lag_artikkel())
    med = html.render(lag_artikkel(sections=(Section("Funn", (lag_graf(),)),)))

    assert "graf-spek" not in uten
    assert "graf-boble" not in uten
    assert "graf-spek" in med
    assert "graf-boble" in med


def test_grafen_har_png_bare_i_noscript(katalog: Path) -> None:
    """Uten skript er PNG-en figuren. Med skript skal den aldri lastes ned."""
    markup = html.render(lag_artikkel(sections=(Section("Funn", (lag_graf(),)),)))

    assert '<noscript><img src="graf.png"' in markup
    assert markup.count('<img src="graf.png"') == 1
    # Skriptet trenger å vite hva det skal falle tilbake på hvis det ryker.
    assert 'data-fallback="graf.png"' in markup


def test_grafspesifikasjonen_kan_ikke_lukke_script_elementet(katalog: Path) -> None:
    """Et merkenavn er data. Kommer det fra en kilde, kan det inneholde hva som helst.

    Spesifikasjonen ligger i et rått script-element, som slutter på det første
    ``</``. Klarer et kommunenavn å skrive det, eier det resten av sida.
    """
    stygg = lag_graf(
        marks=(Mark(label='</script><script>alert(1)</script>', tone="vekst"),),
    )
    markup = html.render(lag_artikkel(sections=(Section("Funn", (stygg,)),)))

    assert "</script><script>alert(1)" not in markup
    assert "\\u003c/script" in markup
    # …og det skal fortsatt være gyldig JSON som gir navnet tilbake uendret.
    spek = markup.split('class="graf-spek">')[1].split("</script>")[0]
    assert json.loads(spek)["marks"][0]["label"] == '</script><script>alert(1)</script>'


# --------------------------------------------------------------------------
# Publisering
# --------------------------------------------------------------------------
def test_publisering_skriver_side_arkiv_og_vedlegg(katalog: Path) -> None:
    art = lag_artikkel()
    lag_pakke(io.project_root(), art)

    skrevet = site.publish_all()

    side = io.docs_dir() / art.slug / "index.html"
    assert side in skrevet
    assert side.exists()
    assert (io.docs_dir() / art.slug / "graf.png").exists()
    assert (io.docs_dir() / art.slug / "data.csv").exists()
    # Kopien av spesifikasjonen er det arkivet bygges av.
    assert (io.docs_dir() / art.slug / "artikkel.json").exists()
    assert (io.docs_dir() / ".nojekyll").exists()

    arkiv = (io.docs_dir() / "index.html").read_text(encoding="utf-8")
    assert "En testsak" in arkiv
    assert f'href="{art.slug}/index.html"' in arkiv


def test_arkivet_bygges_av_docs_ikke_av_output(katalog: Path) -> None:
    """``output/`` er gitignorert. Det som er publisert, er det som ligger i docs/."""
    lag_pakke(io.project_root(), lag_artikkel())
    site.publish_all()

    for rest in (io.output_dir() / "testsak").iterdir():
        rest.unlink()
    site.write_index()

    assert "En testsak" in (io.docs_dir() / "index.html").read_text(encoding="utf-8")


def test_sakspakke_uten_spesifikasjon_sier_fra(katalog: Path) -> None:
    (io.output_dir() / "gammel_sak").mkdir(parents=True)

    with pytest.raises(site.PublishError, match="artikkel.json"):
        site.publish_all(["gammel_sak"])


def test_ukjent_sakspakke_sier_fra(katalog: Path) -> None:
    lag_pakke(io.project_root(), lag_artikkel())

    with pytest.raises(site.PublishError, match="Klare: testsak"):
        site.publish_all(["skrivefeil"])


def test_ingenting_å_publisere_sier_fra(project: Path) -> None:
    with pytest.raises(site.PublishError, match="Fant ingen sakspakker"):
        site.publish_all()
