"""Ende-til-ende for befolkningskjeden, mot en oppdiktet SSB-respons.

Poenget med å bygge svaret selv i stedet for å hente fra SSB er at vi vet
fasiten. Seriene er utledet av ``PERIODE_AAR``, så testene følger med hvis
perioden endres, og hver kommune finnes for å teste én egenskap:

    kommune          serie                          hva den tester
    0301 Oslo        1000, +10 i året               vanlig vekst, restledd
    3101 Halden       500,  -5 i året               nedgang
    3105 Sarpsborg  10000, +20 og ett hopp på +20   lite avvik: beholdes
    3107 Fredrikstad 1000, +10 og ett hopp på +60   stort avvik: utelates
    1508 Ålesund      300,  +5 og ett hopp på -100  kommunedeling
    1580 Haram          0 til delingen, så 100      motparten, uten historikk

Ålesund og Haram er den ekte delingen i miniatyr, og er grunnen til at
modellen finnes. Sarpsborg og Fredrikstad ligger på hver sin side av
toleransen, som er det som skiller en grensejustering fra et seriebrudd.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from statman import io, registry
from statman.models.mart_befolkning import PERIODE_AAR, TOLERANSE

SLUTT_AAR = 2026
AAR = [str(SLUTT_AAR - PERIODE_AAR + i) for i in range(PERIODE_AAR + 1)]
CONTENTS = ["Folkemengde", "Fodselsoverskudd", "Nettoinnflytting", "Folketilvekst"]

# Året grensene flytter seg, som indeks i AAR. Avviket vises på denne raden,
# mens folkemengden hopper året etter.
DELING = PERIODE_AAR - 3
DELING_AAR = int(AAR[DELING])

# Personer som ligger i SSBs samlekategori og ikke i noen kommune, fram til
# delingen. Fylkestabellen har dem med; kommunetabellen ikke.
UFORDELT = 50


def _serie(
    start: int, aarlig: int | list[int], hopp: dict[int, int] | None = None
) -> tuple[list[int], list[int]]:
    """Folkemengde per 1.1. og folketilveksten SSB ville rapportert.

    ``hopp`` er personer som bytter kommune uten å flytte. De endrer
    folkemengden, men ikke folketilveksten — som er nøyaktig det modellen
    skal oppdage.
    """
    hopp = hopp or {}
    per_aar = [aarlig] * PERIODE_AAR if isinstance(aarlig, int) else list(aarlig)
    folkemengde = [start]
    for i, endring in enumerate(per_aar):
        folkemengde.append(folkemengde[-1] + endring + hopp.get(i, 0))
    return folkemengde, per_aar


KOMMUNER: dict[str, tuple[str, tuple[list[int], list[int]]]] = {
    "K_0301": ("Oslo", _serie(1000, 10)),
    "K_3101": ("Halden", _serie(500, -5)),
    "K_3105": ("Sarpsborg", _serie(10_000, 20, {2: 20})),
    "K_3107": ("Fredrikstad", _serie(1000, 10, {4: 60})),
    "K_1508": ("Ålesund", _serie(300, 5, {DELING: -100})),
    "K_1580": (
        "Haram",
        _serie(0, [0] * (DELING + 1) + [2] * (PERIODE_AAR - DELING - 1), {DELING: 100}),
    ),
    "K_Rest": ("Delte kommuner og uoppgitt", ([0] * (PERIODE_AAR + 1), [0] * PERIODE_AAR)),
}
FYLKER = {"F_03": "Oslo", "F_31": "Østfold", "F_15": "Møre og Romsdal"}
FYLKE_AV = {"K_0301": "F_03", "K_3101": "F_31", "K_3105": "F_31", "K_3107": "F_31",
            "K_1508": "F_15", "K_1580": "F_15"}


def _komponenter(tilvekst: list[int]) -> tuple[list[int], list[int]]:
    """Del tilveksten i to, og la det bli 1 person til overs i andre år."""
    fodsel = [t // 2 for t in tilvekst]
    flytting = [t - f for t, f in zip(tilvekst, fodsel)]
    flytting[1] -= 1
    return fodsel, flytting


def _kommune_doc() -> dict[str, Any]:
    verdier: list[int | None] = []
    for folkemengde, tilvekst in (serie for _, serie in KOMMUNER.values()):
        fodsel, flytting = _komponenter(tilvekst)
        verdier += [*folkemengde]
        verdier += [*fodsel, None]
        verdier += [*flytting, None]
        verdier += [*tilvekst, None]
    return _doc(
        list(KOMMUNER), {kode: navn for kode, (navn, _) in KOMMUNER.items()}, verdier
    )


def _fylke_doc() -> dict[str, Any]:
    """Fylkesserien er summen av kommunene *pluss* de ufordelte personene.

    Slik er det hos SSB også, og differansen er det sakspakken rapporterer.
    """
    verdier: list[int | None] = []
    for fylke in FYLKER:
        koder = [k for k, f in FYLKE_AV.items() if f == fylke]
        folkemengde = [
            sum(KOMMUNER[k][1][0][i] for k in koder) for i in range(PERIODE_AAR + 1)
        ]
        tilvekst = [sum(KOMMUNER[k][1][1][i] for k in koder) for i in range(PERIODE_AAR)]
        if fylke == "F_31":  # de ufordelte legges til ett fylke, som hos SSB
            folkemengde = [n + (UFORDELT if i <= DELING else 0) for i, n in enumerate(folkemengde)]
        fodsel, flytting = _komponenter(tilvekst)
        verdier += [*folkemengde]
        verdier += [*fodsel, None]
        verdier += [*flytting, None]
        verdier += [*tilvekst, None]
    return _doc(list(FYLKER), FYLKER, verdier)


def _doc(koder: list[str], navn: dict[str, str], verdier: list[Any]) -> dict[str, Any]:
    return {
        "class": "dataset",
        "version": "2.0",
        "label": "06913: Befolkning og endringer, etter region og år",
        "source": "Statistisk sentralbyrå",
        "updated": "2026-04-15T06:00:00Z",
        "id": ["Region", "ContentsCode", "Tid"],
        "size": [len(koder), len(CONTENTS), len(AAR)],
        "dimension": {
            "Region": {
                "category": {
                    "index": {kode: i for i, kode in enumerate(koder)},
                    "label": {kode: navn[kode] for kode in koder},
                }
            },
            "ContentsCode": {
                "category": {
                    "index": {c: i for i, c in enumerate(CONTENTS)},
                    "label": {c: c for c in CONTENTS},
                }
            },
            "Tid": {
                "category": {
                    "index": {aar: i for i, aar in enumerate(AAR)},
                    "label": {aar: aar for aar in AAR},
                }
            },
        },
        "value": verdier,
    }


def _skriv_raa() -> None:
    for dataset, doc in (("06913_kommune", _kommune_doc()), ("06913_fylke", _fylke_doc())):
        io.write_raw("ssb", dataset, json.dumps(doc).encode("utf-8"), {"license": "test"})


@pytest.fixture
def built(project: Path) -> dict[str, registry.BuildResult]:
    _skriv_raa()
    targets = ["mart.befolkningsvekst", "mart.befolkning_fylke_aar"]
    return {r.name: r for r in registry.build(targets)}


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------
def test_build_covers_the_whole_chain(built: dict[str, registry.BuildResult]) -> None:
    assert set(built) == {
        "clean.befolkning_kommune",
        "clean.befolkning_fylke",
        "mart.befolkning_kommune_aar",
        "mart.befolkning_fylke_aar",
        "mart.befolkningsvekst",
    }


def test_clean_drops_the_non_municipality_categories(
    built: dict[str, registry.BuildResult],
) -> None:
    """K_Rest er en samlekategori, ikke en kommune."""
    df = io.load("clean.befolkning_kommune")

    assert set(df["kommunenummer"].unique()) == {"0301", "3101", "3105", "3107", "1508", "1580"}
    assert df["kommunenummer"].str.len_chars().max() == 4


def test_clean_strips_the_codelist_prefix_and_types_the_year(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("clean.befolkning_kommune")

    assert df.schema["aar"] == pl.Int32
    assert not any(k.startswith("K_") for k in df["kommunenummer"].to_list())
    assert set(df["variabel"].unique()) == {
        "folkemengde",
        "fodselsoverskudd",
        "nettoinnflytting",
        "folketilvekst",
    }


def test_clean_strips_the_county_prefix(built: dict[str, registry.BuildResult]) -> None:
    """Fylkeskodelista prefikser med F_, ikke K_."""
    df = io.load("clean.befolkning_fylke")

    assert set(df["fylkesnummer"].unique()) == {"03", "31", "15"}


def test_clean_keeps_only_reported_cells(built: dict[str, registry.BuildResult]) -> None:
    """Strømmene mangler for siste år; de radene skal ikke finnes."""
    df = io.load("clean.befolkning_kommune")
    siste = df.filter(pl.col("aar") == SLUTT_AAR)

    assert set(siste["variabel"].unique()) == {"folkemengde"}


# --------------------------------------------------------------------------
# mart: årstabellene
# --------------------------------------------------------------------------
def test_year_table_joins_county_names(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.befolkning_kommune_aar")
    fylke = dict(zip(df["kommunenummer"].to_list(), df["fylke"].to_list()))

    assert fylke["0301"] == "Oslo"
    assert fylke["3101"] == "Østfold"
    assert fylke["1508"] == "Møre og Romsdal"


def test_year_table_has_one_row_per_municipality_year(
    built: dict[str, registry.BuildResult],
) -> None:
    assert built["mart.befolkning_kommune_aar"].rows == 6 * len(AAR)


def test_county_table_is_not_a_rollup_of_the_municipalities(
    built: dict[str, registry.BuildResult],
) -> None:
    """Fylkestallene skal ha med personene som ikke ligger i noen kommune."""
    fylke = io.load("mart.befolkning_fylke_aar")
    kommune = io.load("mart.befolkning_kommune_aar")

    for aar, forventet in ((int(AAR[0]), UFORDELT), (SLUTT_AAR, 0)):
        f = fylke.filter(pl.col("aar") == aar)["folkemengde"].sum()
        k = kommune.filter(pl.col("aar") == aar)["folkemengde"].sum()
        assert f - k == forventet, f"året {aar}"


def test_residual_is_kept_not_swallowed(built: dict[str, registry.BuildResult]) -> None:
    """Vi la inn 1 person restledd i andre år. Den skal stå der."""
    df = io.load("mart.befolkning_kommune_aar")
    rad = df.filter(
        (pl.col("kommunenummer") == "0301") & (pl.col("aar") == int(AAR[1]))
    ).row(0, named=True)

    assert rad["restledd"] == 1
    assert rad["folketilvekst"] == rad["fodselsoverskudd"] + rad["nettoinnflytting"] + 1


def test_annual_rates_use_the_population_at_the_start_of_the_year(
    built: dict[str, registry.BuildResult],
) -> None:
    """Ratene skal måles mot folkemengden 1. januar, ikke mot noe snitt."""
    df = io.load("mart.befolkning_kommune_aar")
    rad = df.filter(
        (pl.col("kommunenummer") == "0301") & (pl.col("aar") == int(AAR[0]))
    ).row(0, named=True)

    assert rad["folkemengde"] == 1000
    assert rad["vekst_pst"] == pytest.approx(10 / 1000)
    assert rad["fodselsoverskudd_pst"] == pytest.approx(rad["fodselsoverskudd"] / 1000)
    assert rad["nettoinnflytting_pst"] == pytest.approx(rad["nettoinnflytting"] / 1000)


def test_annual_rates_are_null_without_a_population_to_divide_by(
    built: dict[str, registry.BuildResult],
) -> None:
    """Haram har 0 innbyggere før delingen. Da finnes det ingen rate."""
    df = io.load("mart.befolkning_kommune_aar")
    haram = df.filter((pl.col("kommunenummer") == "1580") & (pl.col("aar") <= DELING_AAR))

    assert haram["vekst_pst"].null_count() == haram.height
    assert df.filter(pl.col("vekst_pst").is_infinite()).height == 0


def test_border_change_shows_up_in_the_year_it_happened(
    built: dict[str, registry.BuildResult],
) -> None:
    """Avviket står på raden for året før folkemengden hopper."""
    df = io.load("mart.befolkning_kommune_aar")
    par = df.filter(pl.col("kommunenummer").is_in(["1508", "1580"]) & (pl.col("grenseavvik") != 0))

    assert par.height == 2
    assert set(par["aar"].to_list()) == {DELING_AAR}
    assert sorted(par["grenseavvik"].to_list()) == [-100, 100]


def test_stable_municipalities_have_no_grenseavvik(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.befolkning_kommune_aar").filter(
        pl.col("kommunenummer").is_in(["0301", "3101"]) & pl.col("grenseavvik").is_not_null()
    )

    assert (df["grenseavvik"] == 0).all()


# --------------------------------------------------------------------------
# mart: periodetabellen
# --------------------------------------------------------------------------
def test_table_spans_the_intended_period(built: dict[str, registry.BuildResult]) -> None:
    df = io.load("mart.befolkningsvekst")

    assert built["mart.befolkningsvekst"].rows == 6
    assert df["aar_start"].unique().to_list() == [SLUTT_AAR - PERIODE_AAR]
    assert df["aar_slutt"].unique().to_list() == [SLUTT_AAR]


def test_growth_is_the_difference_between_the_two_measurements(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.befolkningsvekst")
    oslo = df.filter(pl.col("kommunenummer") == "0301").row(0, named=True)

    assert oslo["folkemengde_start"] == 1000
    assert oslo["folkemengde_slutt"] == 1000 + 10 * PERIODE_AAR
    assert oslo["vekst"] == 10 * PERIODE_AAR
    assert oslo["vekst_pst"] == pytest.approx(10 * PERIODE_AAR / 1000)


def test_a_small_boundary_change_stays_comparable(
    built: dict[str, registry.BuildResult],
) -> None:
    """20 personer ut av 10 000 er støy, ikke seriebrudd."""
    df = io.load("mart.befolkningsvekst")
    rad = df.filter(pl.col("kommunenummer") == "3105").row(0, named=True)

    assert rad["grenseavvik_sum"] == 20
    assert rad["grenseavvik_maks_pst"] < TOLERANSE
    assert rad["sammenlignbar"] is True


def test_a_large_boundary_change_is_excluded(built: dict[str, registry.BuildResult]) -> None:
    """60 personer ut av 1 000 er et seriebrudd."""
    df = io.load("mart.befolkningsvekst")
    rad = df.filter(pl.col("kommunenummer") == "3107").row(0, named=True)

    assert rad["grenseavvik_sum"] == 60
    assert rad["grenseavvik_maks_pst"] > TOLERANSE
    assert rad["sammenlignbar"] is False


def test_missing_history_is_counted_and_excluded(
    built: dict[str, registry.BuildResult],
) -> None:
    """Haram har ingen folketall før delingen, og kan ikke sammenlignes."""
    df = io.load("mart.befolkningsvekst")
    haram = df.filter(pl.col("kommunenummer") == "1580").row(0, named=True)
    oslo = df.filter(pl.col("kommunenummer") == "0301").row(0, named=True)

    assert haram["aar_uten_folketall"] == DELING + 1
    assert haram["sammenlignbar"] is False
    assert oslo["aar_uten_folketall"] == 0


def test_split_municipalities_are_flagged_not_comparable(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.befolkningsvekst")
    flagg = dict(zip(df["kommunenummer"].to_list(), df["sammenlignbar"].to_list()))

    assert flagg == {
        "0301": True,
        "3101": True,
        "3105": True,
        "3107": False,
        "1508": False,
        "1580": False,
    }


def test_the_two_sides_of_a_split_cancel(built: dict[str, registry.BuildResult]) -> None:
    """En kommunedeling flytter folk; den skaper og ødelegger dem ikke."""
    df = io.load("mart.befolkningsvekst")
    avvik = dict(zip(df["kommunenummer"].to_list(), df["grenseavvik_sum"].to_list()))

    assert avvik["1508"] == -100
    assert avvik["1580"] == 100
    assert avvik["1508"] + avvik["1580"] == 0


def test_ranking_covers_comparable_municipalities_only(
    built: dict[str, registry.BuildResult],
) -> None:
    df = io.load("mart.befolkningsvekst")
    rang = dict(zip(df["kommunenummer"].to_list(), df["rangering"].to_list()))

    assert rang["0301"] == 1  # +150 av 1 000
    assert rang["3105"] == 2  # +320 av 10 000
    assert rang["3101"] == 3  # -75 av 500
    assert rang["3107"] is None
    assert rang["1508"] is None
    assert rang["1580"] is None


def test_flows_are_summed_over_the_period_not_the_measurements(
    built: dict[str, registry.BuildResult],
) -> None:
    """Femten strømår, ikke seksten — siste måleår har ingen strøm ennå."""
    df = io.load("mart.befolkningsvekst")
    oslo = df.filter(pl.col("kommunenummer") == "0301").row(0, named=True)

    assert oslo["aar_med_stromtall"] == PERIODE_AAR
    assert oslo["folketilvekst_sum"] == 10 * PERIODE_AAR
    assert oslo["restledd_sum"] == 1
    assert (
        oslo["fodselsoverskudd_sum"] + oslo["nettoinnflytting_sum"] + oslo["restledd_sum"]
        == oslo["vekst"]
    )


def test_growth_always_equals_flows_plus_border_movement(
    built: dict[str, registry.BuildResult],
) -> None:
    """Identiteten skal holde for *alle* kommuner, også de utelatte."""
    df = io.load("mart.befolkningsvekst")

    assert (df["vekst"] == df["folketilvekst_sum"] + df["grenseavvik_sum"]).all()


def test_a_missing_year_breaks_the_build(project: Path) -> None:
    """Et hull i årsrekka gjør både summene og grenseavviket meningsløse.

    Det skal stoppe bygget, ikke gi en tabell som ser riktig ut.
    """
    doc = _kommune_doc()
    behold = [i for i in range(len(AAR)) if i != 3]
    doc["size"][2] = len(behold)
    doc["dimension"]["Tid"]["category"]["index"] = {AAR[i]: n for n, i in enumerate(behold)}
    doc["dimension"]["Tid"]["category"]["label"] = {AAR[i]: AAR[i] for i in behold}
    doc["value"] = [v for i, v in enumerate(_kommune_doc()["value"]) if i % len(AAR) != 3]

    io.write_raw("ssb", "06913_kommune", json.dumps(doc).encode("utf-8"), {"license": "test"})
    io.write_raw("ssb", "06913_fylke", json.dumps(_fylke_doc()).encode("utf-8"), {"license": "test"})

    with pytest.raises(registry.CheckFailed, match="aar_med_stromtall"):
        registry.build(["mart.befolkningsvekst"])


# --------------------------------------------------------------------------
# Sakspakken
# --------------------------------------------------------------------------
def test_sakspakke_is_written(built: dict[str, registry.BuildResult], project: Path) -> None:
    real_catalog = Path(__file__).resolve().parent.parent / "catalog" / "metrics.yml"
    (project / "catalog").mkdir(exist_ok=True)
    (project / "catalog" / "metrics.yml").write_text(
        real_catalog.read_text(encoding="utf-8"), encoding="utf-8"
    )

    from examples import befolkningsvekst

    written = befolkningsvekst.main()
    navn = {p.name for p in written}

    assert navn == {
        "befolkningsvekst_kommune.csv",
        "vekst_topp_bunn.png",
        "aarlig_utvikling.png",
        "aarlig_ekstremer.png",
        "komponenter.png",
        "fylke.png",
        "notat.md",
    }
    assert all(p.exists() and p.stat().st_size > 0 for p in written)
    for png in (p for p in written if p.suffix == ".png"):
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    notat = next(p for p in written if p.suffix == ".md").read_text(encoding="utf-8")
    assert "## Funn" in notat
    assert "## Metode" in notat
    assert "## Forbehold" in notat
    # Forbeholdene skal komme fra katalogen, ikke være skrevet på nytt her.
    assert "Prosentvekst er ustabil i små kommuner" in notat
    # De utelatte kommunene skal navngis, ikke bare telles.
    assert "Ålesund" in notat and "Haram" in notat
    # De ufordelte personene skal rapporteres, ikke forsvinne i stillhet.
    assert f"{UFORDELT} personer mangler i kommunetabellen" in notat

    csv = pl.read_csv(next(p for p in written if p.suffix == ".csv"))
    assert csv.height == 6


def test_axis_labels_keep_a_decimal_when_the_ticks_need_one() -> None:
    """En akse med halvprosent-merker skal ikke stå med «1, 1, 0, 0»."""
    from examples.befolkningsvekst import _akse_pst

    assert _akse_pst(0.02) == "2 %"
    assert _akse_pst(0.005) == "0,5 %"
    assert _akse_pst(-0.015) == "-1,5 %"
    assert _akse_pst(0.0) == "0 %"
    assert _akse_pst(-0.0) == "0 %"


def test_extremes_are_ranked_on_share_not_headcount() -> None:
    """Utvalget skal være prosentendring. Ellers ville lista blitt de fem
    største kommunene, som er en helt annen sak."""
    from examples.befolkningsvekst import N_EKSTREM, _ekstremer

    df = pl.DataFrame(
        {
            "kommunenummer": ["1", "2", "3", "4", "5", "6"],
            # Kommune 6 har flest personer, men lavest andel.
            "nettoinnflytting_sum": [50, 40, 30, 20, 10, 900],
            "folkemengde_start": [100, 100, 100, 100, 100, 100_000],
        }
    )
    topp, bunn = _ekstremer(df, "nettoinnflytting_sum", 1)

    assert topp["kommunenummer"].to_list() == ["1"]
    assert bunn["kommunenummer"].to_list() == ["6"]
    assert N_EKSTREM == 5


def test_kort_navn_strips_the_other_languages() -> None:
    from examples.befolkningsvekst import kort_navn

    assert kort_navn("Troms - Romsa - Tromssa") == "Troms"
    assert kort_navn("Innlandet") == "Innlandet"


def test_label_does_not_repeat_a_county_already_in_the_name() -> None:
    from examples.befolkningsvekst import _etikett

    assert _etikett({"kommune": "Frøya", "fylke": "Trøndelag - Trööndelage"}) == "Frøya (Trøndelag)"
    assert _etikett({"kommune": "Våler (Østfold)", "fylke": "Østfold"}) == "Våler (Østfold)"
