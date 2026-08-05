"""Tests for the generated ontology, its topology, and the sample-data generator.

An ontology is a claim about the world that nothing forces to stay true. These tests exist
because the generated extensions assert things that are checkable — "this class is
materialised by dbt model X", "this connector supplies concept Y" — and an assertion nobody
checks is the failure mode ontologies are famous for.

Three properties are pinned:

1. **It parses.** Turtle that does not load is not an ontology, and a generator emitting it
   fails silently — the files are there and look plausible.
2. **It matches the project.** Every `conn:dbtModel` names a model in the manifest; every
   `implemented` connector is in the registry. The generator reports drift, and this makes
   the report a gate.
3. **It invents nothing.** A `planned` connector has no source tables. Sample data uses only
   values from `ontology/reference/`. Both are rule 5, mechanically enforced.

rdflib and sqlglot are optional; the tests that need them skip rather than fail, matching
`tests/test_dbt_column_lineage.py`.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ontology_generator as og  # noqa: E402
import dbt_seed_generator as seeder  # noqa: E402

USE_CASE = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
ONTOLOGY = USE_CASE / "ontology"
MANIFEST = USE_CASE / "dbt_project/target/manifest.json"

needs_ontology = pytest.mark.skipif(
    not (ONTOLOGY / "connectors.yml").exists(), reason="enhanza-analytics not on this branch"
)
needs_manifest = pytest.mark.skipif(
    not MANIFEST.exists(), reason="no parsed manifest; run artifacts/refresh.sh"
)

try:
    from rdflib import Graph
    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover - optional
    HAVE_RDFLIB = False

needs_rdflib = pytest.mark.skipif(not HAVE_RDFLIB, reason="rdflib not installed (optional)")


# ---------------------------------------------------------------------------------------
# It parses
# ---------------------------------------------------------------------------------------


@needs_ontology
@needs_rdflib
@pytest.mark.parametrize(
    "path",
    sorted(ONTOLOGY.rglob("*.ttl")) if ONTOLOGY.exists() else [],
    ids=lambda p: p.name,
)
def test_every_turtle_file_parses(path: Path) -> None:
    Graph().parse(path, format="turtle")


@needs_ontology
@needs_rdflib
def test_the_core_is_not_empty() -> None:
    graph = Graph()
    for name in ("erp.ttl", "crm.ttl", "connector.ttl"):
        graph.parse(ONTOLOGY / "core" / name, format="turtle")
    assert len(graph) > 200, f"core ontology has only {len(graph)} triples"


# ---------------------------------------------------------------------------------------
# It matches the project
# ---------------------------------------------------------------------------------------


@needs_ontology
@needs_manifest
@pytest.mark.skipif(
    __import__("dbt_column_lineage").sqlglot is None,
    reason="committed ontology carries sqlglot-derived mappings; regenerating without it "
           "is refused by the downgrade guard, not a drift signal",
)
def test_generation_is_current() -> None:
    """A hand edit, or a project change nobody regenerated for, fails here."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/ontology_generator.py"),
         "--use-case", "enhanza-analytics", "--check", "--format", "json"],
        capture_output=True, text=True, timeout=300,
    )
    payload = json.loads(result.stdout)
    assert not payload["files_changed"], (
        f"regeneration would change {payload['files_changed']} — run "
        f"scripts/ontology_generator.py"
    )
    assert not payload["problems"], payload["problems"]


@needs_ontology
@needs_manifest
def test_every_declared_dbt_model_exists() -> None:
    """The property that makes this ontology falsifiable rather than decorative."""
    from _manifest import Manifest

    man = Manifest.load(str(MANIFEST))
    known = {n.get("name") for n in man.nodes.values() if n.get("resource_type") == "model"}
    missing: list[str] = []
    for path in sorted((ONTOLOGY / "connectors").glob("*.ttl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "conn:dbtModel" in line:
                name = line.split('"')[1]
                if name not in known:
                    missing.append(f"{path.name}: {name}")
    assert not missing, f"ontology names models that do not exist: {missing[:5]}"


@needs_ontology
def test_catalogue_and_registry_agree() -> None:
    specs = og.read_catalogue(ONTOLOGY / "connectors.yml")
    registry = og.read_registry(USE_CASE / "dbt_project")
    implemented = {s.key for s in specs if s.status == "implemented"}
    assert implemented == set(registry), (
        f"catalogue-only: {sorted(implemented - set(registry))}; "
        f"registry-only: {sorted(set(registry) - implemented)}"
    )


@needs_ontology
def test_every_concept_has_a_core_class() -> None:
    """An unclassified concept means the generator would have to guess. It must not."""
    specs = og.read_catalogue(ONTOLOGY / "connectors.yml")
    registry = og.read_registry(USE_CASE / "dbt_project")
    concepts = {c for entry in registry.values() for c in entry["concepts"]}
    concepts |= {c for s in specs for c in s.expected_concepts}
    unclassified = sorted(concepts - set(og.CONCEPT_CLASS))
    assert not unclassified, f"add to CONCEPT_CLASS in ontology_generator.py: {unclassified}"


# ---------------------------------------------------------------------------------------
# It invents nothing
# ---------------------------------------------------------------------------------------


@needs_ontology
def test_planned_connectors_assert_no_source_tables() -> None:
    """Rule 5. A planned connector's schema is unknown, so it is not written down."""
    specs = {s.key: s for s in og.read_catalogue(ONTOLOGY / "connectors.yml")}
    offenders: list[str] = []
    for path in sorted((ONTOLOGY / "connectors").glob("*.ttl")):
        spec = specs.get(path.stem)
        if not spec or spec.status != "planned":
            continue
        text = path.read_text(encoding="utf-8")
        if "conn:sourceTable" in text or "conn:sourceColumn" in text:
            offenders.append(path.name)
    assert not offenders, f"planned connectors with invented schema: {offenders}"


@needs_ontology
def test_planned_connectors_are_marked_needs_input() -> None:
    specs = {s.key: s for s in og.read_catalogue(ONTOLOGY / "connectors.yml")}
    for path in sorted((ONTOLOGY / "connectors").glob("*.ttl")):
        spec = specs.get(path.stem)
        if not spec or spec.status != "planned" or not spec.expected_concepts:
            continue
        assert "[NEEDS INPUT]" in path.read_text(encoding="utf-8"), path.name


@needs_ontology
def test_class_aware_mapping_rejects_a_wrong_class() -> None:
    """`ArticleNumber -> erp:partyNumber` says an Article is a Party. It was generated once."""
    assert og.property_for("ArticleNumber", "erp:Article") == "erp:resourceNumber"
    assert og.property_for("ArticleNumber", "erp:Customer") is None
    assert og.property_for("CustomerNumber", "erp:Customer") == "erp:partyNumber"
    assert og.property_for("CustomerNumber", "erp:Article") is None
    # A rule with no class restriction applies everywhere.
    assert og.property_for("OrgId", "erp:Article") == "erp:orgId"


def test_local_class_name_is_singular_and_camel() -> None:
    assert og._local("fact_invoice_rows") == "InvoiceRow"
    assert og._local("dim_customers") == "Customer"
    assert og._local("dim_company") == "Company"


def test_words_spells_a_camel_local_the_way_the_core_spells_it() -> None:
    assert og._words("InvoiceRow") == "Invoice Row"
    assert og._words("SupplierInvoiceAccrual") == "Supplier Invoice Accrual"
    assert og._words("Account") == "Account"


@needs_ontology
def test_every_generated_class_carries_a_label_qualified_by_its_connector() -> None:
    """Found by running an external OWL linter over the committed tree: 169 of 223 classes
    had no `rdfs:label`, all of them generated. The core vocabulary labels every class.

    Qualified by the connector because the collision is the design: ten connectors each
    declare an `Account`, so ten classes labelled "Account" are not distinguishable by the
    one property whose job is to distinguish them.
    """
    spec = og.ConnectorSpec(key="acme", name="Acme", kind="erp", status="implemented")
    spec.concepts = ["fact_invoice_rows"]
    turtle = og.render_connector(spec)
    assert 'acme:InvoiceRow a owl:Class ;' in turtle
    assert 'rdfs:label "Acme Invoice Row"@en ;' in turtle


@needs_ontology
@needs_rdflib
def test_no_committed_class_is_unlabelled() -> None:
    """The gate for the above, over the artifact rather than the renderer."""
    from rdflib import Graph, RDF, RDFS
    from rdflib.namespace import OWL

    graph = Graph()
    for path in sorted(ONTOLOGY.rglob("*.ttl")):
        graph.parse(path, format="turtle")
    unlabelled = [
        str(c) for c in graph.subjects(RDF.type, OWL.Class)
        if not list(graph.objects(c, RDFS.label))
    ]
    assert not unlabelled, f"{len(unlabelled)} classes carry no rdfs:label: {unlabelled[:5]}"


# ---------------------------------------------------------------------------------------
# Per-use-case configuration
# ---------------------------------------------------------------------------------------


@needs_ontology
def test_the_namespace_is_pinned_not_derived() -> None:
    """The hand-authored core already publishes these IRIs.

    A namespace derived from the slug would be `https://w3id.org/enhanza-analytics/`, and
    every generated `rdfs:subClassOf erp:Customer` would then point at a class the core does
    not define — an ontology that parses, resolves nothing, and says so nowhere.
    """
    cfg = og.read_config(ONTOLOGY, "enhanza-analytics")
    assert cfg.namespace == "https://w3id.org/enhanza/"
    core = (ONTOLOGY / "core" / "erp.ttl").read_text(encoding="utf-8")
    assert cfg.erp in core, "generated IRIs must match the hand-authored core"


def test_a_missing_config_falls_back_without_raising(tmp_path: Path) -> None:
    cfg = og.read_config(tmp_path, "toy")
    assert cfg.namespace == og.DEFAULT_NAMESPACE
    assert cfg.concept_class == og.CONCEPT_CLASS


def test_a_namespace_without_a_separator_gets_one(tmp_path: Path) -> None:
    """`https://example.org/x` + `erp#` would yield `xerp#` — a silently wrong IRI."""
    (tmp_path / "ontology.yml").write_text(
        "namespace: https://example.org/retail\n", encoding="utf-8"
    )
    cfg = og.read_config(tmp_path, "retail")
    assert cfg.namespace == "https://example.org/retail/"
    assert cfg.erp == "https://example.org/retail/erp#"


def test_use_case_concepts_layer_over_the_shared_map(tmp_path: Path) -> None:
    """A domain's own concept goes in its own file, not in the shared ERP/CRM vocabulary."""
    (tmp_path / "ontology.yml").write_text(
        "namespace: https://example.org/lettings/\n"
        "concept_classes:\n"
        "  dim_leases: erp:Contract\n",
        encoding="utf-8",
    )
    cfg = og.read_config(tmp_path, "lettings")
    assert cfg.concept_class["dim_leases"] == "erp:Contract"
    assert cfg.concept_class["dim_customers"] == "erp:Customer", "shared map still applies"
    assert "dim_leases" not in og.CONCEPT_CLASS, "the shared map must not be mutated"


def test_rendering_honours_the_configured_namespace() -> None:
    cfg = og.OntologyConfig(namespace="https://example.org/retail/")
    spec = og.ConnectorSpec(key="acme", name="Acme", kind="erp", status="implemented")
    spec.concepts = ["dim_customers"]
    turtle = og.render_connector(spec, cfg)
    assert "@prefix acme: <https://example.org/retail/connector/acme#> ." in turtle
    assert "https://w3id.org/enhanza/" not in turtle


# ---------------------------------------------------------------------------------------
# The machine-facing projection
# ---------------------------------------------------------------------------------------


@needs_ontology
def test_the_index_exists_and_carries_every_documented_key() -> None:
    index = json.loads((ONTOLOGY / "index.json").read_text(encoding="utf-8"))
    for tool in index["mcp_tools"]:
        assert tool["backed_by"] in index, (
            f"tool {tool['tool']} is backed by '{tool['backed_by']}', which the index "
            f"does not carry — a server would fail at request time"
        )
    assert index["connectors"] and index["concepts"]


@needs_ontology
@needs_manifest
def test_index_and_turtle_agree_on_every_model() -> None:
    """The projection cannot lead the graph, or serving it would mean serving a third truth."""
    index = json.loads((ONTOLOGY / "index.json").read_text(encoding="utf-8"))
    from_index = {(m["connector"], m["dbt_model"]) for m in index["models"]}

    from_turtle: set[tuple[str, str]] = set()
    for path in sorted((ONTOLOGY / "connectors").glob("*.ttl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "conn:dbtModel" in line:
                from_turtle.add((path.stem, line.split('"')[1]))
    assert from_index == from_turtle, (
        f"only in index: {sorted(from_index - from_turtle)[:5]}; "
        f"only in turtle: {sorted(from_turtle - from_index)[:5]}"
    )


@needs_ontology
@needs_manifest
def test_index_and_turtle_agree_on_every_column_mapping() -> None:
    index = json.loads((ONTOLOGY / "index.json").read_text(encoding="utf-8"))
    from_index = {(m["connector"], m["property"], m["source_column"]) for m in index["mappings"]}

    from_turtle: set[tuple[str, str, str]] = set()
    for path in sorted((ONTOLOGY / "connectors").glob("*.ttl")):
        prop = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if "conn:mapsToProperty" in line:
                prop = line.split()[-2]
            elif "conn:sourceColumn" in line and prop:
                from_turtle.add((path.stem, prop, line.split('"')[1]))
                prop = None
    assert from_index == from_turtle


@needs_ontology
def test_the_index_states_its_own_provenance() -> None:
    """A served `resolve_column` answer built on a partial parse must not look complete."""
    index = json.loads((ONTOLOGY / "index.json").read_text(encoding="utf-8"))
    provenance = index["provenance"]
    assert "column_lineage_available" in provenance
    if provenance["column_lineage_available"]:
        assert provenance["models_parsed"], "lineage claimed available with nothing parsed"
        assert "models_parse_failed" in provenance, "failures must be countable, not implied"


@needs_ontology
def test_a_single_supplier_concept_is_reported_as_a_gap() -> None:
    """One supplier is not conformance — a number from it cannot be compared across tenants."""
    index = json.loads((ONTOLOGY / "index.json").read_text(encoding="utf-8"))
    gap_names = {g["concept"] for g in index["gaps"]}
    for concept in index["concepts"]:
        if concept["supplier_count"] <= 1:
            assert concept["concept"] in gap_names, concept["concept"]
        else:
            assert concept["concept"] not in gap_names, concept["concept"]


@needs_ontology
def test_planned_connectors_reach_the_index_without_models_or_mappings() -> None:
    """Rule 5 again, on the served side: a planned connector asserts scope, not schema."""
    index = json.loads((ONTOLOGY / "index.json").read_text(encoding="utf-8"))
    planned = {c["key"] for c in index["connectors"] if c["status"] == "planned"}
    assert planned, "no planned connectors to check"
    assert not {m["connector"] for m in index["models"]} & planned
    assert not {m["connector"] for m in index["mappings"]} & planned


# ---------------------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------------------


@needs_ontology
def test_reference_data_loads() -> None:
    ref = seeder.Reference(ONTOLOGY / "reference")
    assert ref.orgs and ref.customers and ref.suppliers and ref.employees and ref.articles


@needs_ontology
def test_generated_values_come_from_reference_data() -> None:
    """No invented business names — the Ontology-Playground convention and rule 5."""
    ref = seeder.Reference(ONTOLOGY / "reference")
    names = {p["PartyName"] for p in ref.parties}
    numbers = {p["PartyNumber"] for p in ref.parties}
    for row in range(12):
        assert seeder.cell("Name", row, ref) in names
        assert seeder.cell("CustomerNumber", row, ref) in numbers
        assert seeder.cell("OrgId", row, ref) in {o["OrgId"] for o in ref.orgs}


@needs_ontology
def test_unmapped_columns_get_a_visibly_fake_placeholder() -> None:
    """A placeholder that looks like data is worse than one that does not."""
    ref = seeder.Reference(ONTOLOGY / "reference")
    value = seeder.cell("SomeUnknownField", 0, ref)
    assert value == "someunknownfield_value_1"


@needs_ontology
def test_generation_is_deterministic() -> None:
    """Same manifest, byte-identical output — so a diff always means the project changed."""
    ref = seeder.Reference(ONTOLOGY / "reference")
    first = [seeder.cell("InvoiceDate", r, ref) for r in range(12)]
    second = [seeder.cell("InvoiceDate", r, ref) for r in range(12)]
    assert first == second
    assert len(set(first)) == 12, "dates must be distinct or ordering tests are vacuous"


@needs_ontology
def test_numeric_placeholders_are_never_zero() -> None:
    """A zero in sample data hides division and share-of-total bugs."""
    ref = seeder.Reference(ONTOLOGY / "reference")
    for column in ("Amount", "TotalPrice", "Quantity"):
        for row in range(12):
            assert float(seeder.cell(column, row, ref)) != 0.0


@needs_ontology
@needs_manifest
def test_seed_column_order_is_total() -> None:
    """Sorting on `c.lower()` alone leaves case-colliding names tied, and the input is a set.

    Two of 99 seeds flapped between runs before the tiebreak was added, because set iteration
    order varies with PYTHONHASHSEED and a stable sort preserves whatever order it received.
    The determinism claim in the generator's docstring was simply false, and the visible cost
    is the diff that teaches a reviewer to ignore generated files.
    """
    columns = {"OrgId", "Id", "ID", "Name", "name"}
    key = lambda c: (c != "OrgId", c.lower(), c)  # noqa: E731 - mirrors build_seeds
    keys = [key(c) for c in columns]
    assert len(set(keys)) == len(keys), "sort key must be total over the column set"
    assert sorted(columns, key=key)[0] == "OrgId", "the tenant key stays first"


@needs_ontology
@needs_manifest
def test_seeds_are_byte_identical_across_hash_seeds() -> None:
    """The property the flapping bug broke, checked end to end rather than at the sort key."""
    import os

    def render(hash_seed: str) -> dict:
        # Different seeds on purpose: identical ones cannot expose an ordering that depends
        # on set iteration, which is exactly the defect this pins.
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "import json, dbt_seed_generator as g;"
             "from pathlib import Path;"
             "from _manifest import Manifest;"
             f"man = Manifest.load({str(MANIFEST)!r});"
             f"ref = g.Reference(Path({str(ONTOLOGY / 'reference')!r}));"
             "print(json.dumps(g.build_seeds(man, ref, None)))"],
            capture_output=True, text=True, cwd=REPO, env=env, timeout=600,
        )
        if proc.returncode != 0:
            pytest.skip(f"seed generation unavailable: {proc.stderr.strip()[-200:]}")
        return json.loads(proc.stdout)

    first = render("1")
    if not first:
        pytest.skip("no seeds resolved (sqlglot not installed)")
    assert first == render("12345")


@needs_ontology
@needs_manifest
def test_properties_bind_every_seed_to_its_source_relation() -> None:
    """The wiring: alias strips the filename prefix, schema is the source name.

    With the project's generate_schema_name() and the demo target, that lands each seed at
    exactly the relation `source()` resolves to under `uid: demo`. A seed without its
    properties entry floats to the default schema and the source lookup misses it.
    """
    seed_dir = USE_CASE / "dbt_project/seeds/sample"
    if not (seed_dir / "properties.yml").exists():
        pytest.skip("sample seeds not generated in this checkout")
    text = (seed_dir / "properties.yml").read_text(encoding="utf-8")
    for path in sorted(seed_dir.glob("*.csv")):
        stem = path.stem
        source_name, table = stem.split("__", 1)
        assert f"- name: {stem}" in text, f"{stem} has no properties entry"
        assert f"alias: {table}" in text
        assert f"schema: {source_name}" in text
    # The production backstop: sample seeds must not be loadable outside the demo target.
    assert text.count("enabled: \"{{ target.name == 'demo' }}\"") == len(
        list(seed_dir.glob("*.csv"))
    )


@needs_ontology
@needs_manifest
def test_every_seed_column_is_pinned_varchar() -> None:
    """Two type inferrers (agate, the warehouse sniffer) disagreed on the first real load.

    Raw API landing tables are string-typed and staging casts explicitly (rule 15), so the
    seed declares varchar for every column and no inference happens at all.
    """
    seed_dir = USE_CASE / "dbt_project/seeds/sample"
    if not (seed_dir / "properties.yml").exists():
        pytest.skip("sample seeds not generated in this checkout")
    text = (seed_dir / "properties.yml").read_text(encoding="utf-8")
    total_columns = sum(
        len(path.read_text(encoding="utf-8").splitlines()[0].split(","))
        for path in seed_dir.glob("*.csv")
    )
    assert text.count(": varchar") == total_columns


@needs_ontology
@needs_manifest
def test_no_seed_declares_case_colliding_columns() -> None:
    """`DueDate` in one model and `duedate` in another are one physical column.

    BigQuery resolves column references case-insensitively, so both spellings hit the same
    column; a seed that declares both is rejected by DuckDB outright ("Column with name
    enz_sync_ts already exists"). Four seeds did exactly that before folding.
    """
    seed_dir = USE_CASE / "dbt_project/seeds/sample"
    if not seed_dir.exists():
        pytest.skip("sample seeds not generated in this checkout")
    for path in sorted(seed_dir.glob("*.csv")):
        header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
        lowered = [c.lower() for c in header]
        assert len(set(lowered)) == len(lowered), f"{path.name}: case-colliding columns"


@needs_ontology
@needs_manifest
def test_seed_columns_cover_what_the_sql_references_not_just_output_lineage() -> None:
    """A column read into a CTE and discarded by the final select is still *selected*.

    The seventime adapter reads `unitPrice` into a CTE column its outer select drops, so
    output lineage — correctly — has no edge for it, and a seed built from lineage alone
    fails the build on a missing column. Seeds must satisfy references, not lineage.
    """
    import dbt_column_lineage as lineage_mod

    if lineage_mod.sqlglot is None:
        pytest.skip("sqlglot not installed (optional)")
    seed_dir = USE_CASE / "dbt_project/seeds/sample"
    seed = seed_dir / "seventime_api__expenseitems.csv"
    if not seed.exists():
        pytest.skip("sample seeds not generated in this checkout")
    header = seed.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "unitPrice" in header, "CTE-only column reads must reach the seed"
    # And the jinja-span case: a column read only inside a macro argument.
    products = (seed_dir / "shopify_api__products.csv").read_text(encoding="utf-8")
    assert "variant_sku" in products.splitlines()[0]


@needs_ontology
@needs_manifest
def test_seeds_are_valid_csv_with_stable_width() -> None:
    seed_dir = USE_CASE / "dbt_project/seeds/sample"
    if not seed_dir.exists():
        pytest.skip("sample seeds not generated in this checkout")
    files = sorted(seed_dir.glob("*.csv"))
    assert files, "no seed files"
    for path in files:
        rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
        assert len(rows) == seeder.ROWS_PER_TABLE + 1, path.name
        width = len(rows[0])
        assert all(len(r) == width for r in rows), f"ragged CSV: {path.name}"


@needs_ontology
@needs_manifest
def test_the_tenant_key_is_consistent_wherever_it_appears() -> None:
    """Cross-table joins in the sample data only work if OrgId means the same thing everywhere.

    Not "every seed has OrgId" — 30 of 99 source tables genuinely do not carry one, because
    their staging models pick the tenant up through a join or, in the demo layer, synthesize
    it. Asserting presence would be asserting something false about the project and would
    have to be suppressed rather than fixed. What must hold is that the seeds which *do*
    carry it draw from one set of tenants, or nothing joins.
    """
    seed_dir = USE_CASE / "dbt_project/seeds/sample"
    if not seed_dir.exists():
        pytest.skip("sample seeds not generated in this checkout")
    ref = seeder.Reference(ONTOLOGY / "reference")
    known = {o["OrgId"] for o in ref.orgs}

    seen: set[str] = set()
    for path in sorted(seed_dir.glob("*.csv")):
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
        if not rows or "OrgId" not in rows[0]:
            continue
        values = {r["OrgId"] for r in rows}
        assert values <= known, f"{path.name} has org ids outside the reference file: {values - known}"
        seen |= values
    assert seen == known, (
        f"reference organisations never used in any seed: {sorted(known - seen)} — "
        f"an unused tenant makes multi-tenant filtering untested"
    )
