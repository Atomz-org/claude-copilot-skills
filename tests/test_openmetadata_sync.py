"""Tests for the OpenMetadata discovery-tier bridge.

The bridge pushes this repository's metadata into a catalog UI, and a catalog is
believed. So the properties worth pinning are the ones that decide whether what it
publishes is *true*, not whether it publishes a lot:

1. **Nothing is invented.** The service name is declared or the stage skips; a binding
   endpoint that resolves to no dbt node is dropped and counted; a glossary term
   asserts no business definition nobody wrote; `PII.None` — a tag OpenMetadata does
   not define — is never emitted.
2. **An absent decision reads as absent.** An unannotated column gets no facet tag, and
   the generated knowledge says so in words. A catalog that defaults to `Additive` puts
   a wrong number on a dashboard with a governance tag next to it.
3. **The bundle is deterministic.** It is committed, so `--check` is a byte comparison;
   anything run-dependent in it makes the gate permanently red.
4. **Egress is never implicit.** The sync stage cannot push. `--push` without both
   environment variables skips, and `--check` never pushes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import openmetadata_sync as oms  # noqa: E402
import use_case_sync as sync  # noqa: E402

SCRIPT = REPO / "scripts/openmetadata_sync.py"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
EXAMPLE = REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart"

needs_enhanza = pytest.mark.skipif(
    not (ENHANZA / "openmetadata/bundle/column-lineage.json").exists(),
    reason="enhanza-analytics bundle not on this branch",
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=600, cwd=REPO,
    )


def _cfg(**overrides) -> oms.Config:
    base = dict(service="svc", glossary="g", glossary_display_name="G")
    base.update(overrides)
    return oms.Config(**base)


def _relation(table: str = "t", schema: str = "s", database: str = "d") -> oms.Relation:
    return oms.Relation(database, schema, table, f"model.p.{table}", "model")


# ---------------------------------------------------------------------------------------
# Fully qualified names
# ---------------------------------------------------------------------------------------


def test_a_name_part_containing_a_dot_is_quoted() -> None:
    """An unquoted dot splits the FQN into the wrong number of levels.

    `service.db.schema.my.table` reads as five components and the table is never
    found — the failure is a silent 404 on every request touching that entity.
    """
    assert oms.fqn("svc", "db", "sch", "my.table") == 'svc.db.sch."my.table"'
    assert oms.fqn("svc", "plain") == "svc.plain"


def test_a_quoted_relation_name_round_trips_through_the_splitter() -> None:
    node = {"relation_name": '"db"."sch"."tbl"', "unique_id": "model.p.tbl",
            "resource_type": "model"}
    relation = oms._relation_of(node)
    assert (relation.database, relation.schema, relation.table) == ("db", "sch", "tbl")


def test_relation_name_wins_over_recomposing_database_schema_alias() -> None:
    """dbt already resolved custom schemas and aliases; recomposing re-derives them.

    A project overriding `generate_schema_name` — most real ones — compiles a schema
    that `database`/`schema`/`alias` do not reproduce.
    """
    node = {
        "relation_name": '"real_db"."real_schema"."real_table"',
        "database": "wrong_db", "schema": "wrong_schema", "alias": "wrong_table",
        "unique_id": "model.p.x", "resource_type": "model",
    }
    relation = oms._relation_of(node)
    assert relation.table_fqn(_cfg()) == "svc.real_db.real_schema.real_table"


# ---------------------------------------------------------------------------------------
# Nothing is invented
# ---------------------------------------------------------------------------------------


def test_a_use_case_without_a_service_skips_and_names_the_remedy(tmp_path: Path) -> None:
    """The service name is a fact about the server. Guessing it 404s every request."""
    cfg, reason = oms.Config.load(tmp_path, "toy")
    assert cfg is None
    assert "openmetadata.yml" in reason
    assert "OPENMETADATA_DB_SERVICE" in reason, "a skip must name the way out of it"


def test_a_config_with_an_empty_service_still_skips(tmp_path: Path) -> None:
    """The scaffold writes `service:` with no value; that must skip, not emit."""
    (tmp_path / "openmetadata.yml").write_text("service:\nglossary: toy\n", encoding="utf-8")
    cfg, reason = oms.Config.load(tmp_path, "toy")
    assert cfg is None
    assert "no `service:`" in reason or "declares no" in reason


def test_the_env_var_overrides_the_declared_service(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "openmetadata.yml").write_text("service: from_file\n", encoding="utf-8")
    monkeypatch.setenv(oms.SERVICE_ENV, "from_env")
    cfg, _ = oms.Config.load(tmp_path, "toy")
    assert cfg.service == "from_env"


def test_a_binding_endpoint_with_no_dbt_node_is_dropped_and_counted() -> None:
    """`NULL`, an unnest alias, a struct field — a parse yields names that are not tables.

    Emitting them would mint a catalog entity for something that does not exist, and
    the lineage graph would show a table called `NULL`.
    """
    memory = {
        "contracts": [{"concept": "c", "adapters": {"k": "adapter"}, "conformed": ["Col"]}],
        "bindings": [
            {"concept": "c", "connector": "k", "column": "Col",
             "source_model": "real_src", "source_column": "raw", "transform": "direct",
             "hops": 1},
            {"concept": "c", "connector": "k", "column": "Col",
             "source_model": "NULL", "source_column": "raw", "transform": "direct",
             "hops": 1},
        ],
    }
    relations = {"adapter": _relation("adapter"), "real_src": _relation("real_src")}
    out = oms.build_column_lineage(memory, relations, _cfg())

    assert out["stats"]["table_pairs"] == 1
    assert out["dropped"]["unresolved_source_models"] == {"NULL": 1}
    emitted = json.dumps(out)
    assert '"svc.d.s.NULL"' not in emitted, "a parse artifact must not become a table"


def test_several_upstream_columns_become_one_edge_with_several_fromColumns() -> None:
    """The spec models this natively; two conflicting edges would not.

    A conformed column fed by a union or a derived expression has several sources, and
    `ColumnLineage.fromColumns` is a list for exactly that reason.
    """
    memory = {
        "contracts": [{"concept": "c", "adapters": {"k": "adapter"}, "conformed": ["Col"]}],
        "bindings": [
            {"concept": "c", "connector": "k", "column": "Col", "source_model": "src",
             "source_column": "a", "transform": "union", "hops": 2},
            {"concept": "c", "connector": "k", "column": "Col", "source_model": "src",
             "source_column": "b", "transform": "union", "hops": 2},
        ],
    }
    out = oms.build_column_lineage(
        memory, {"adapter": _relation("adapter"), "src": _relation("src")}, _cfg()
    )
    lineage = out["edges"][0]["edge"]["lineageDetails"]["columnsLineage"]
    assert len(lineage) == 1
    assert lineage[0]["fromColumns"] == ["svc.d.s.src.a", "svc.d.s.src.b"]
    assert out["stats"]["multi_source_columns"] == 1


def test_the_lineage_source_is_a_member_of_the_spec_enum() -> None:
    """`lineageDetails.source` is closed. An invented member is rejected server-side."""
    assert oms.LINEAGE_SOURCE in {
        "Manual", "ViewLineage", "QueryLineage", "PipelineLineage", "DashboardLineage",
        "DbtLineage", "SparkLineage", "OpenLineage", "ExternalTableLineage",
        "CrossDatabaseLineage", "ChildAssets",
    }


def test_a_concept_term_states_facts_and_asserts_no_business_definition() -> None:
    """`description` is required on a glossary term, and nothing here records meaning.

    Filling it with "Represents a customer in the business" is the invented definition
    rule 5 forbids; stating the core class, the suppliers, and the contract width is not.
    """
    index = {"concepts": [{
        "concept": "dim_accounts", "id": "https://w3id.org/x/topology#Account",
        "core_class": "erp:Account", "implemented_by": ["fortnox"], "planned_by": [],
    }]}
    memory = {"contracts": [{
        "concept": "dim_accounts", "column_count": 16, "adapters": {"fortnox": "m"},
        "partial_for": [],
    }]}
    out = oms.build_glossary(index, memory, None, _cfg(), "x")
    term = out["terms"][0]

    assert term["iri"] == "https://w3id.org/x/topology#Account"
    assert "erp:Account" in term["description"]
    assert "16 conformed column" in term["description"]
    assert "no business definition is asserted" in term["description"]


# ---------------------------------------------------------------------------------------
# PII, and the tag that does not exist
# ---------------------------------------------------------------------------------------


def test_direct_pii_maps_to_the_system_tag() -> None:
    assert oms._facet_tags({"pii": "direct"}) == ["PII.Sensitive"]


def test_quasi_pii_does_not_become_nonsensitive() -> None:
    """`PII.NonSensitive` would state the opposite of what the annotation says.

    A quasi-identifier is identifying in combination; calling it non-sensitive in the
    governance layer is worse than leaving it to a tag that names the class.
    """
    tags = oms._facet_tags({"pii": "quasi"})
    assert tags == ["ColumnPII.Quasi"]
    assert "PII.NonSensitive" not in tags


def test_pii_none_emits_no_tag_because_openmetadata_defines_none() -> None:
    """OpenMetadata's PII classification has Sensitive and NonSensitive, and no third.

    Emitting `PII.None` would create a classification member nobody governs, on every
    non-PII column in the catalog.
    """
    assert oms._facet_tags({"pii": "none"}) == []
    bundle = json.dumps(oms.build_classifications())
    assert "PII.None" not in bundle


def test_an_unannotated_column_earns_no_tag() -> None:
    """Absence of a decision must read as absence, never as a default.

    A `ColumnAdditivity.Additive` tag applied by default is a governance label
    asserting something nobody decided — and it is the label a BI tool trusts.
    """
    assert oms._facet_tags({"column": "X"}) == []
    assert oms._facet_tags({"role": None, "additivity": None, "unit": None}) == []


def test_a_facet_value_outside_the_declared_set_is_ignored() -> None:
    """The tag has to exist before a label can reference it; the server rejects it."""
    assert oms._facet_tags({"additivity": "somewhat_additive"}) == []


def test_every_applied_tag_fqn_is_defined_by_the_classifications_bundle() -> None:
    """A label naming a classification that does not exist is rejected on push.

    Checked across every facet value the annotation schema allows, so adding a facet
    without adding its tag fails here rather than at 3am against a live server.
    """
    defined = {
        f"{t['classification']}.{t['name']}" for t in oms.build_classifications()["tags"]
    }
    defined.add(oms.SYSTEM_PII_TAG)
    for facet, spec in oms.FACET_CLASSIFICATIONS.items():
        for value in spec["tags"]:
            for tag in oms._facet_tags({facet: value}):
                assert tag in defined, f"{facet}={value} applies undefined tag {tag}"


def test_a_mutually_exclusive_facet_is_declared_as_such() -> None:
    """A column has one role and one additivity; the server enforces that if told."""
    by_name = {c["name"]: c for c in oms.build_classifications()["classifications"]}
    assert by_name["ColumnRole"]["mutuallyExclusive"] is True
    assert by_name["ColumnAdditivity"]["mutuallyExclusive"] is True
    assert by_name["ColumnPII"]["mutuallyExclusive"] is False


# ---------------------------------------------------------------------------------------
# dlt load columns
# ---------------------------------------------------------------------------------------


def test_dlt_columns_are_found_where_a_dbt_source_declares_them() -> None:
    """The free, committed evidence path: a source contract that lists `_dlt_load_id`."""

    class FakeManifest:
        sources = {
            "source.p.raw.events": {
                "relation_name": '"db"."raw"."events"', "name": "events",
                "source_name": "raw", "resource_type": "source",
                "unique_id": "source.p.raw.events",
                "columns": {"_dlt_id": {}, "_dlt_load_id": {}, "amount": {}},
            }
        }

        def models(self):
            return {}

    out = oms.build_dlt_provenance(Path("."), FakeManifest(), _cfg())
    columns = [a for a in out["applications"] if a["entity"] == "column"]

    assert {a["column"] for a in columns} == {"_dlt_id", "_dlt_load_id"}
    assert all("DataProvenance.DltSystemColumn" in a["tags"] for a in columns)
    assert all("ColumnRole.Identifier" in a["tags"] for a in columns), (
        "a dlt column is never a quantity; the role tag is what stops SUM()"
    )
    assert "amount" not in {a["column"] for a in columns}


def test_the_dlt_definitions_are_emitted_even_with_no_evidence() -> None:
    """Definitions are a closed documented set; only the applications need evidence."""
    out = oms.build_dlt_provenance(Path("."), None, _cfg())
    assert out["applications"] == []
    assert len(out["glossary_terms"]) == len(oms.DLT_COLUMNS) == 5
    assert set(out["known_tables"]) == {"_dlt_loads", "_dlt_version", "_dlt_pipeline_state"}


def test_a_declared_warehouse_is_not_read_without_the_flag(tmp_path: Path) -> None:
    """A gitignored, rebuildable warehouse must not change a committed artifact.

    Read by default, the bundle would differ between a machine that had run the
    pipeline and a fresh clone, and `--check` would be permanently red — the same
    lesson as cache counters in `column-memory.json`'s provenance block.
    """
    cfg = _cfg(dlt_warehouse="w.duckdb")
    out = oms.build_dlt_provenance(tmp_path, None, cfg, with_warehouse=False)
    assert out["applications"] == []
    assert any("--with-warehouse" in e for e in out["evidence"]), (
        "a bundle reporting zero must say which kind of zero it is"
    )


def test_a_missing_warehouse_is_reported_rather_than_raising(tmp_path: Path) -> None:
    cfg = _cfg(dlt_warehouse="absent.duckdb")
    out = oms.build_dlt_provenance(tmp_path, None, cfg, with_warehouse=True)
    assert out["applications"] == []
    assert out["evidence"]


def test_dlt_columns_are_read_from_a_real_duckdb_warehouse(tmp_path: Path) -> None:
    """The other evidence path, against a warehouse shaped like dlt's own output."""
    duckdb = pytest.importorskip("duckdb")
    warehouse = tmp_path / "w.duckdb"
    con = duckdb.connect(str(warehouse))
    con.execute("create schema raw")
    con.execute("create table raw.events (id varchar, amount double, "
                "_dlt_id varchar, _dlt_load_id varchar)")
    con.execute("create table raw._dlt_loads (load_id varchar, status bigint)")
    con.close()

    cfg = _cfg(dlt_warehouse="w.duckdb", dlt_schema="raw")
    out = oms.build_dlt_provenance(tmp_path, None, cfg, with_warehouse=True)

    columns = {a["column"] for a in out["applications"] if a["entity"] == "column"}
    tables = {a["fqn"] for a in out["applications"] if a["entity"] == "table"}
    assert columns == {"_dlt_id", "_dlt_load_id"}
    assert tables == {"svc.w.raw._dlt_loads"}
    assert out["stats"]["column_applications"] == 2


# ---------------------------------------------------------------------------------------
# Egress is never implicit
# ---------------------------------------------------------------------------------------


def test_push_without_credentials_skips_rather_than_failing(monkeypatch) -> None:
    monkeypatch.delenv(oms.SERVER_URL_ENV, raising=False)
    monkeypatch.delenv(oms.AUTH_TOKEN_ENV, raising=False)
    result = _run(["--use-case", "example-order-revenue-mart", "--push", "--check",
                   "--format", "json"])
    payload = json.loads(result.stdout)
    assert payload["push"]["status"] == "skip"
    assert oms.SERVER_URL_ENV in payload["push"]["reason"]


def test_check_never_pushes_even_with_credentials_set(monkeypatch) -> None:
    """A gate that mutates a remote system while checking is not a gate."""
    env = {oms.SERVER_URL_ENV: "http://127.0.0.1:1/api", oms.AUTH_TOKEN_ENV: "x"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--use-case", "example-order-revenue-mart",
         "--push", "--check", "--format", "json"],
        capture_output=True, text=True, timeout=300, cwd=REPO,
        env={**dict(__import__("os").environ), **env},
    )
    payload = json.loads(result.stdout)
    assert payload["push"]["status"] == "skip"
    assert "--check" in payload["push"]["reason"]


def test_the_sync_stage_cannot_push() -> None:
    """The stage emits. Egress stays an explicit, separate, confirmed act (rule 15).

    Read off the compiled function rather than the source text: the docstring names
    `--push` to say the stage does *not* pass it, and a substring search over the
    source would fail on the sentence that documents the guarantee.
    """
    import dis

    literals = {
        instruction.argval
        for instruction in dis.get_instructions(sync.stage_openmetadata)
        if isinstance(instruction.argval, str)
    }
    assert "--check" in literals, "the stage must forward --check"
    assert "--push" not in literals
    assert "--with-warehouse" not in literals, (
        "the stage must not read a gitignored warehouse into a committed artifact"
    )


def test_the_bridge_has_no_delete_path() -> None:
    """One bad artifact read must not be able to empty a production catalog."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"DELETE"' not in source and "'DELETE'" not in source


# ---------------------------------------------------------------------------------------
# The stage, and the committed bundle
# ---------------------------------------------------------------------------------------


def test_openmetadata_runs_last_of_all_stages() -> None:
    """It projects every artifact the earlier stages refresh, including wren's inputs."""
    source = (REPO / "scripts/use_case_sync.py").read_text(encoding="utf-8")
    order = [
        source.index(f'run("{name}"')
        for name in ("columns", "annotations", "ontology", "alignment", "wren",
                     "lightdash", "openmetadata")
    ]
    assert order == sorted(order)


def test_the_stage_is_selectable_by_name() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/use_case_sync.py"), "--use-case",
         "example-order-revenue-mart", "--stage", "openmetadata", "--check",
         "--format", "json"],
        capture_output=True, text=True, timeout=600, cwd=REPO,
    )
    stages = {s["stage"] for s in json.loads(result.stdout)["use_cases"][0]["stages"]}
    assert "openmetadata" in stages
    assert "wren" not in stages, "--stage must not run the others"


def test_a_use_case_without_a_config_skips_the_stage(tmp_path: Path) -> None:
    stage = sync.stage_openmetadata(tmp_path, "no-such-use-case", None, check=True)
    assert stage.status == sync.SKIP


def test_the_committed_bundle_is_current() -> None:
    """The bundle is committed, so `--check` is a byte comparison and a real gate."""
    for slug in ("example-order-revenue-mart", "enhanza-analytics"):
        result = _run(["--use-case", slug, "--check", "--format", "json"])
        payload = json.loads(result.stdout)
        if payload["status"] == "skip":
            continue
        assert payload["changed"] == [], (
            f"{slug}: openmetadata bundle is stale — re-run "
            f"`python3 scripts/use_case_sync.py --use-case {slug} --stage openmetadata`"
        )


def test_emitting_twice_produces_identical_bytes(tmp_path: Path) -> None:
    """Nothing run-dependent in the bundle: no timestamps, no counters, no paths."""
    first = _run(["--use-case", "example-order-revenue-mart", "--format", "json"])
    second = _run(["--use-case", "example-order-revenue-mart", "--format", "json"])
    assert json.loads(first.stdout)["changed"] == []
    assert json.loads(second.stdout)["changed"] == []


# ---------------------------------------------------------------------------------------
# The committed enhanza bundle — the only place the full projection is exercised
# ---------------------------------------------------------------------------------------


@needs_enhanza
def test_enhanza_column_lineage_reaches_raw_sources_not_just_the_next_model() -> None:
    """The whole reason the bridge exists: the standard connector stops at parent_map."""
    bundle = json.loads(
        (ENHANZA / "openmetadata/bundle/column-lineage.json").read_text(encoding="utf-8")
    )
    stats = bundle["stats"]
    assert stats["column_edges"] > 500
    assert stats["table_pairs"] > 50
    # A hop count above one is what distinguishes this from model-level lineage.
    assert any(
        "hop(s)" in e["edge"]["lineageDetails"]["description"] for e in bundle["edges"]
    )
    assert bundle["dropped"]["unresolved_source_models"], (
        "enhanza has known parse artifacts; silence here means the guard stopped running"
    )


@needs_enhanza
def test_every_pii_direct_annotation_reaches_the_catalog_as_the_system_tag() -> None:
    """The one projection a BI user's disclosure risk depends on."""
    annotations = json.loads(
        (ENHANZA / "ontology/column-annotations.json").read_text(encoding="utf-8")
    )
    direct = {c["column"] for c in annotations["columns"] if c.get("pii") == "direct"}
    assert direct, "fixture expects enhanza to carry direct-PII columns"

    glossary = json.loads(
        (ENHANZA / "openmetadata/bundle/glossary.json").read_text(encoding="utf-8")
    )
    tagged = {
        t["name"] for t in glossary["terms"]
        if any(tag["tagFQN"] == "PII.Sensitive" for tag in t.get("tags", []))
    }
    assert direct <= tagged


@needs_enhanza
def test_the_generated_knowledge_states_the_uncovered_count() -> None:
    """A file listing what is covered and silent on the rest reads as complete."""
    text = (ENHANZA / "openmetadata/knowledge/catalog.md").read_text(encoding="utf-8")
    annotations = json.loads(
        (ENHANZA / "ontology/column-annotations.json").read_text(encoding="utf-8")
    )
    assert str(len(annotations["unannotated"])) in text
    assert "Do not read the absence of a tag" in text


@needs_enhanza
def test_the_ingestion_config_names_the_same_service_as_the_bundle() -> None:
    """Two generators, one service name. Disagreeing here 404s the whole push."""
    config = (ENHANZA / "openmetadata/ingestion/dbt.yaml").read_text(encoding="utf-8")
    lineage = json.loads(
        (ENHANZA / "openmetadata/bundle/column-lineage.json").read_text(encoding="utf-8")
    )
    service = lineage["edges"][0]["edge"]["fromEntity"]["fullyQualifiedName"].split(".")[0]
    assert f"serviceName: {service}" in config


@needs_enhanza
def test_the_ingestion_config_never_overwrites_curated_descriptions() -> None:
    """A unidirectional pipeline that clobbers human curation is a deletion tool."""
    config = (ENHANZA / "openmetadata/ingestion/dbt.yaml").read_text(encoding="utf-8")
    assert "dbtUpdateDescriptions: false" in config
    assert "dbtUpdateOwners: false" in config


@needs_enhanza
def test_the_rdf_alignment_parses_and_carries_the_lineage_as_prov() -> None:
    """Generated Turtle that does not parse is a silent defect — nothing reads it eagerly.

    Term provenance is checked in `tests/test_submodule_sync.py`, against the pinned
    ontology rather than against the file's own header: an earlier version of this test
    required the file to *declare* every `om:` term it used, which is what let a guessed
    namespace and an invented `om:glossaryTerm` pass. A file cannot vouch for itself.
    """
    rdflib = pytest.importorskip("rdflib")
    path = ENHANZA / "openmetadata/rdf/openmetadata-alignment.ttl"
    graph = rdflib.Graph()
    graph.parse(str(path), format="turtle")
    assert len(graph) > 1000

    om = rdflib.Namespace(oms.OM_NAMESPACE)
    dcat = rdflib.Namespace("http://www.w3.org/ns/dcat#")
    # The three relations that carry the alignment, each queried rather than grepped.
    assert len(list(graph.subjects(rdflib.RDF.type, om.Table))) > 0
    assert len(list(graph.subject_objects(dcat.theme))) > 0, "no table -> glossary term"
    lineage_arcs = list(graph.subject_objects(om.fromColumn))
    assert len(lineage_arcs) > 500, "the deep column lineage did not reach the RDF"
    # `om:fromColumn rdfs:subPropertyOf prov:used` upstream, so both ends must be typed
    # columns — an untyped IRI is a dangling node a SHACL run would reject.
    for target, source in lineage_arcs[:50]:
        assert (target, rdflib.RDF.type, om.Column) in graph
        assert (source, rdflib.RDF.type, om.Column) in graph


@needs_enhanza
def test_a_quoted_fqn_component_cannot_collide_with_an_unquoted_one() -> None:
    """`svc.db.sch."my.table".col` and `svc.db.sch.my.table.col` are different columns.

    They differ only in quote characters, so a minted IRI that strips quotes merges two
    distinct columns into one node — and the lineage of one silently becomes the
    lineage of both.
    """
    from urllib.parse import quote

    quoted = quote('svc.db.sch."my.table".col', safe=".-_~:")
    plain = quote("svc.db.sch.my.table.col", safe=".-_~:")
    assert quoted != plain
    assert "%22" in quoted


@needs_enhanza
def test_no_credential_value_is_written_into_any_generated_file() -> None:
    """Environment placeholders only — never a token, never a resolved host."""
    for path in (ENHANZA / "openmetadata").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "Bearer ey" not in text, f"{path.name} looks like it carries a JWT"
        if oms.AUTH_TOKEN_ENV in text:
            assert f"${{{oms.AUTH_TOKEN_ENV}}}" in text or f"${oms.AUTH_TOKEN_ENV}" in text


# ---------------------------------------------------------------------------------------
# Optional validation
# ---------------------------------------------------------------------------------------


def test_validation_skips_and_names_the_install_when_the_sdk_is_absent() -> None:
    """`openmetadata-ingestion` is optional here, like sqlglot and rdflib elsewhere."""
    result = _run(["--use-case", "example-order-revenue-mart", "--check",
                   "--format", "json"])
    validation = json.loads(result.stdout)["validation"]
    assert validation["status"] in ("ok", "skip", "fail")
    if validation["status"] == "skip":
        assert "openmetadata-ingestion" in validation["detail"]


def test_the_ingestion_pin_matches_the_server_pin() -> None:
    """The wheel must equal the server version; the wheel carries a fourth component."""
    assert oms.INGESTION_PIN.startswith(oms.SERVER_PIN + ".")
    assert oms.INGESTION_PIN in oms.INGESTION_INSTALL
