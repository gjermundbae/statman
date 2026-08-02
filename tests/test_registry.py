from __future__ import annotations

from pathlib import Path

import pytest

from statman import io, registry
from statman.registry import CheckFailed, Context, build, build_order, model


def _noop(ctx: Context) -> None:  # pragma: no cover - registreres, kjøres ikke
    return None


def test_model_registers_with_deps_split(project: Path, isolated_registry: None) -> None:
    model(name="clean.a", deps=["raw:ssb/03013"], doc="A")(_noop)
    spec = registry.registry()["clean.a"]

    assert spec.deps == ("raw:ssb/03013",)
    assert spec.model_deps == ()
    assert spec.raw_deps == ("ssb/03013",)
    assert spec.doc == "A"


def test_model_uses_docstring_when_no_doc(isolated_registry: None) -> None:
    @model(name="clean.doc")
    def with_docstring(ctx: Context) -> None:
        """Første linje.

        Andre avsnitt.
        """

    assert registry.registry()["clean.doc"].doc == "Første linje."


def test_model_rejects_bad_name(isolated_registry: None) -> None:
    with pytest.raises(ValueError):
        model(name="raw.a")(_noop)


def test_model_rejects_duplicate(isolated_registry: None) -> None:
    model(name="clean.dup")(_noop)
    with pytest.raises(ValueError, match="allerede registrert"):
        model(name="clean.dup")(lambda ctx: None)


def test_build_order_is_topological(isolated_registry: None) -> None:
    model(name="clean.a", deps=["raw:x/y"])(_noop)
    model(name="clean.b", deps=["clean.a"])(_noop)
    model(name="mart.c", deps=["clean.a", "clean.b"])(_noop)

    order = build_order(["mart.c"])
    assert order.index("clean.a") < order.index("clean.b") < order.index("mart.c")


def test_build_order_without_targets_covers_everything(isolated_registry: None) -> None:
    model(name="clean.a")(_noop)
    model(name="mart.b", deps=["clean.a"])(_noop)
    assert build_order() == ["clean.a", "mart.b"]


def test_build_order_detects_cycle(isolated_registry: None) -> None:
    model(name="clean.a", deps=["mart.b"])(_noop)
    model(name="mart.b", deps=["clean.a"])(_noop)

    with pytest.raises(ValueError, match="Sykel"):
        build_order(["clean.a"])


def test_build_order_unknown_target(isolated_registry: None) -> None:
    with pytest.raises(KeyError):
        build_order(["mart.finnes_ikke"])


def test_build_order_unknown_dependency(isolated_registry: None) -> None:
    model(name="mart.a", deps=["clean.mangler"])(_noop)
    with pytest.raises(KeyError, match="mangler"):
        build_order(["mart.a"])


def test_view_name() -> None:
    assert Context.view_name("clean.kpi") == "clean_kpi"


def test_context_read_raw_json(project: Path, con) -> None:
    io.write_raw("demo", "ds", b'[{"a": 1}, {"a": 2}]')
    rel = Context(con).read_raw("demo/ds")
    assert sorted(row[0] for row in rel.fetchall()) == [1, 2]


def test_context_read_raw_csv(project: Path, con) -> None:
    io.write_raw("demo", "csvds", b"a,b\n1,x\n2,y\n", suffix="csv")
    ctx = Context(con)
    rel = ctx.read_raw("demo/csvds")
    assert rel.fetchall() == [(1, "x"), (2, "y")]


def test_context_raw_latest_requires_slash(project: Path, con) -> None:
    with pytest.raises(ValueError, match="<kilde>/<datasett>"):
        Context(con).raw_latest("bare_kilde")


def test_context_ref_unbuilt_is_explicit(project: Path, con) -> None:
    with pytest.raises(FileNotFoundError, match="ikke bygget"):
        Context(con).ref("clean.finnes_ikke")


# --------------------------------------------------------------------------
# Sjekker
# --------------------------------------------------------------------------
def _write(project: Path, con, name: str, query: str) -> Path:
    path = io.model_path(name)
    io.write_table(con.sql(query), path)
    return path


def test_checks_pass(project: Path, con) -> None:
    path = _write(project, con, "clean.ok", "select * from (values (1, 'a'), (2, 'b')) t(n, s)")
    registry.run_checks(con, "clean.ok", path, ["unique:n", "not_null:s", "n > 0"])


def test_check_unique_fails(project: Path, con) -> None:
    path = _write(project, con, "clean.dup", "select * from (values (1), (1)) t(n)")
    with pytest.raises(CheckFailed, match="unique:n"):
        registry.run_checks(con, "clean.dup", path, ["unique:n"])


def test_check_unique_on_composite_key(project: Path, con) -> None:
    path = _write(
        project, con, "clean.comp", "select * from (values (1, 'a'), (1, 'b')) t(n, s)"
    )
    registry.run_checks(con, "clean.comp", path, ["unique:n,s"])
    with pytest.raises(CheckFailed):
        registry.run_checks(con, "clean.comp", path, ["unique:n"])


def test_check_not_null_fails(project: Path, con) -> None:
    path = _write(project, con, "clean.nn", "select * from (values (1), (null)) t(n)")
    with pytest.raises(CheckFailed, match="not_null:n"):
        registry.run_checks(con, "clean.nn", path, ["not_null:n"])


def test_check_predicate_counts_nulls_as_violations(project: Path, con) -> None:
    path = _write(project, con, "clean.pred", "select * from (values (1), (null)) t(n)")
    with pytest.raises(CheckFailed, match="n > 0"):
        registry.run_checks(con, "clean.pred", path, ["n > 0"])


# --------------------------------------------------------------------------
# build()
# --------------------------------------------------------------------------
def test_build_runs_in_order_and_materializes(project: Path, isolated_registry: None) -> None:
    @model(name="clean.tall", deps=["raw:demo/tall"], checks=["unique:n"])
    def clean_tall(ctx: Context):
        src = ctx.raw_latest("demo/tall").as_posix()
        return ctx.sql(f"select cast(n as int) as n from read_json_auto('{src}')")

    @model(name="mart.doblet", deps=["clean.tall"], checks=["n2 = n * 2"])
    def mart_doblet(ctx: Context):
        return ctx.sql("select n, n * 2 as n2 from clean_tall")

    io.write_raw("demo", "tall", b'[{"n": 1}, {"n": 2}, {"n": 3}]')
    results = build()

    assert [r.name for r in results] == ["clean.tall", "mart.doblet"]
    assert [r.rows for r in results] == [3, 3]
    assert all(r.path.exists() for r in results)
    assert sorted(io.load("mart.doblet")["n2"].to_list()) == [2, 4, 6]


def test_build_propagates_check_failure(project: Path, isolated_registry: None) -> None:
    @model(name="clean.feil", checks=["n > 100"])
    def clean_feil(ctx: Context):
        return ctx.sql("select * from (values (1), (2)) t(n)")

    with pytest.raises(CheckFailed):
        build(["clean.feil"])


def test_build_rejects_none(project: Path, isolated_registry: None) -> None:
    @model(name="clean.none")
    def clean_none(ctx: Context) -> None:
        return None

    with pytest.raises(TypeError, match="returnerte None"):
        build(["clean.none"])


# --------------------------------------------------------------------------
# En feilet sjekk skal ikke etterlate tall på disk
# --------------------------------------------------------------------------
def test_failed_check_leaves_nothing_behind(project: Path, isolated_registry: None) -> None:
    """«Sjekken stopper bygget» må også bety at de underkjente tallene ikke lagres."""

    @model(name="clean.daarlig", checks=["verdi > 0"])
    def daarlig(ctx: Context):
        return ctx.sql("select 1 as id, -5 as verdi")

    with pytest.raises(CheckFailed):
        build(["clean.daarlig"])

    assert not io.model_path("clean.daarlig").exists()
    assert not io.manifest_path("clean.daarlig").exists()
    # Heller ingen halvferdig fil som en senere kjøring kan snuble i.
    assert list(io.layer_dir("clean").glob("*")) == []


def test_failed_rebuild_keeps_the_previous_good_table(
    project: Path, isolated_registry: None
) -> None:
    """Et mislykket bygg skal ikke ødelegge det som allerede lå der."""
    tilstand = {"verdi": 5}

    @model(name="clean.vaklende", checks=["verdi > 0"])
    def vaklende(ctx: Context):
        return ctx.sql(f"select {tilstand['verdi']} as verdi")

    build(["clean.vaklende"])
    import polars as pl

    assert pl.read_parquet(io.model_path("clean.vaklende"))["verdi"][0] == 5

    tilstand["verdi"] = -1
    with pytest.raises(CheckFailed):
        build(["clean.vaklende"])

    assert pl.read_parquet(io.model_path("clean.vaklende"))["verdi"][0] == 5


def test_a_failing_model_does_not_corrupt_downstream(
    project: Path, isolated_registry: None
) -> None:
    """Nedstrøms modell skal ikke kunne lese tall som ble underkjent."""

    @model(name="clean.kilde", checks=["verdi > 0"])
    def kilde(ctx: Context):
        return ctx.sql("select -5 as verdi")

    @model(name="mart.avledet", deps=["clean.kilde"])
    def avledet(ctx: Context):
        return ctx.sql("select verdi * 2 as verdi from clean_kilde")

    with pytest.raises(CheckFailed):
        build(["mart.avledet"])

    assert not io.model_path("clean.kilde").exists()
    assert not io.model_path("mart.avledet").exists()


# --------------------------------------------------------------------------
# Råavhengigheter valideres før noe kjøres
# --------------------------------------------------------------------------
def test_missing_raw_is_reported_before_anything_runs(
    project: Path, isolated_registry: None
) -> None:
    kjort: list[str] = []

    @model(name="clean.forst")
    def forst(ctx: Context):
        kjort.append("clean.forst")
        return ctx.sql("select 1 as verdi")

    @model(name="mart.senere", deps=["clean.forst", "raw:ssb/finnes_ikke"])
    def senere(ctx: Context):  # pragma: no cover - skal aldri kjøres
        kjort.append("mart.senere")
        return ctx.sql("select 1 as verdi")

    with pytest.raises(registry.MissingRawData, match="ssb/finnes_ikke"):
        build(["mart.senere"])

    assert kjort == [], "ingen modell skal ha kjørt før råsjekken"
    assert not io.model_path("clean.forst").exists()


def test_missing_raw_lists_every_gap_and_who_needs_it(
    project: Path, isolated_registry: None
) -> None:
    @model(name="clean.a", deps=["raw:ssb/mangler_a"])
    def a(ctx: Context):  # pragma: no cover
        return None

    @model(name="clean.b", deps=["raw:ssb/mangler_b"])
    def b(ctx: Context):  # pragma: no cover
        return None

    assert registry.missing_raw(["clean.a", "clean.b"]) == {
        "ssb/mangler_a": ["clean.a"],
        "ssb/mangler_b": ["clean.b"],
    }
    with pytest.raises(registry.MissingRawData) as feil:
        build(["clean.a", "clean.b"])
    assert "ssb/mangler_a" in str(feil.value)
    assert "ssb/mangler_b" in str(feil.value)


def test_missing_raw_points_at_the_neighbours_it_did_find(
    project: Path, isolated_registry: None
) -> None:
    """Skrivefeil i datasettnavnet er den vanligste årsaken. Da hjelper det å se hva som finnes."""
    io.write_raw("ssb", "06913_kommune", b"{}", {"license": "test"})

    @model(name="clean.feilstavet", deps=["raw:ssb/06913_kommuner"])
    def feilstavet(ctx: Context):  # pragma: no cover
        return None

    with pytest.raises(registry.MissingRawData) as feil:
        build(["clean.feilstavet"])
    assert "06913_kommune" in str(feil.value)


# --------------------------------------------------------------------------
# Byggelogg
# --------------------------------------------------------------------------
def test_manifest_records_the_resolved_raw_version(
    project: Path, isolated_registry: None
) -> None:
    """Det er den oppløste versjonen som skal stå, ikke «nyeste».""" 
    forste = io.write_raw("ssb", "sett", b'[{"a": 1}]', {"license": "test"})

    @model(name="clean.fra_raa", deps=["raw:ssb/sett"])
    def fra_raa(ctx: Context):
        return ctx.read_raw("ssb/sett")

    build(["clean.fra_raa"])
    manifest = io.read_manifest("clean.fra_raa")

    assert manifest["model"] == "clean.fra_raa"
    assert manifest["rows"] == 1
    assert manifest["raw"]["ssb/sett"]["version"] == forste.name
    assert manifest["raw"]["ssb/sett"]["sha256"] == io.read_meta(forste)["sha256"]
    assert io.raw_version_dir("ssb/sett", forste.name) == forste

    # En ny henting etterpå skal ikke endre hva den bygde tabellen hviler på.
    io.write_raw("ssb", "sett", b'[{"a": 2}]', {"license": "test"})
    assert io.read_manifest("clean.fra_raa")["raw"]["ssb/sett"]["version"] == forste.name


def test_manifest_inherits_provenance_from_upstream(
    project: Path, isolated_registry: None
) -> None:
    """En mart-tabell skal kunne spores til rådata uten å følge kjeden manuelt."""
    versjon = io.write_raw("ssb", "sett", b'[{"a": 1}]', {"license": "test"})

    @model(name="clean.kilde", deps=["raw:ssb/sett"])
    def kilde(ctx: Context):
        return ctx.read_raw("ssb/sett")

    @model(name="mart.avledet", deps=["clean.kilde"])
    def avledet(ctx: Context):
        return ctx.sql("select a * 10 as a from clean_kilde")

    build(["mart.avledet"])
    manifest = io.read_manifest("mart.avledet")

    assert manifest["model_deps"] == ["clean.kilde"]
    assert manifest["raw"]["ssb/sett"]["version"] == versjon.name


def test_manifest_records_the_checks_that_passed(
    project: Path, isolated_registry: None
) -> None:
    @model(name="clean.sjekket", checks=["verdi > 0", "not_null:verdi"])
    def sjekket(ctx: Context):
        return ctx.sql("select 3 as verdi")

    build(["clean.sjekket"])
    assert io.read_manifest("clean.sjekket")["checks"] == ["verdi > 0", "not_null:verdi"]


def test_read_manifest_says_what_to_do_when_missing(project: Path) -> None:
    with pytest.raises(FileNotFoundError, match="statman build"):
        io.read_manifest("clean.aldri_bygget")
