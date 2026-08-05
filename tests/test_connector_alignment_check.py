"""Tests for the connector alignment checker.

Every check in this script exists because the corresponding defect was found in
enhanza-analytics, so each one is tested against a synthetic reproduction of that defect
rather than against a description of it:

  * `arguments:` nesting under a generic test — dbt >= 1.10 syntax in a project pinned
    below it. One file, and `dbt parse` failed for all 359 models with an error naming a
    test rather than the syntax.
  * Two models resolving to one relation in one schema. 38 aliases were doubly claimed
    because `model_alias()` strips the connector prefix and no `+schema` was declared.
  * A staging directory with no registry entry — it builds, it ships, and `erp_union()`
    never unions it.

The synthetic projects matter for a second reason: `enhanza-analytics` arrives on feature
branches, so a suite that only tested against it would go red depending on which branch is
checked out. Tests that need the real project skip when it is absent, matching
`tests/test_new_connector.py`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import connector_alignment_check as checker  # noqa: E402
import dbt_column_lineage as _lineage  # noqa: E402
import new_connector  # noqa: E402

SCRIPT = REPO / "scripts" / "connector_alignment_check.py"
ENHANZA_SLUG = "enhanza-analytics"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project"

needs_enhanza = pytest.mark.skipif(
    not (ENHANZA / "dbt_project.yml").exists(),
    reason="enhanza-analytics not on this branch",
)
needs_manifest = pytest.mark.skipif(
    not (ENHANZA / "target/manifest.json").exists(),
    reason="no parsed manifest; run artifacts/refresh.sh",
)
# The adapter-column checks parse SQL, so they need the optional parser. Declared here with
# the other markers because the accepted-error gate above uses it too.
needs_sqlglot = pytest.mark.skipif(
    _lineage.sqlglot is None, reason="sqlglot not installed (optional dependency)"
)


# ---------------------------------------------------------------------------------------
# Registry drives the connector list, not the directory listing
# ---------------------------------------------------------------------------------------


@needs_enhanza
def test_registry_is_parsed_from_the_project_macro() -> None:
    conv = new_connector.detect(new_connector.find_use_case(ENHANZA_SLUG))
    registry = checker.registry_connectors(conv)
    assert registry is not None, "registry macro not found"
    assert "fortnox" in registry
    assert "erp" not in registry, "erp is the unified layer, not a source connector"


@needs_enhanza
def test_unified_layer_is_recognised_from_its_tags() -> None:
    conv = new_connector.detect(new_connector.find_use_case(ENHANZA_SLUG))
    assert "erp" in checker.unified_layer_dirs(conv)


@needs_enhanza
def test_unified_layer_is_not_checked_as_a_connector() -> None:
    """It has no `sources:` block by design; checking it reports 28 false defects."""
    findings = checker.run(ENHANZA_SLUG, None, None)
    assert not [f for f in findings if f.connector == "erp"]


# Errors that are known, documented in CONNECTORS.md's drift table, and blocked on an
# answer nobody in this repository has. Listing them here rather than asserting zero keeps
# the gate meaningful: a *new* error still fails, and closing one of these fails too, which
# is the prompt to delete the entry.
ACCEPTED_ERRORS: set = set()
# Empty since the favrit adapter was conformed to the peer contract: ArticleNumber is
# typed NULL (the upsales precedent — Favrit's order line has a product_id and no
# human-facing article code), OrderDate derives from CreatedAt, and the three columns no
# peer carries were dropped from the adapter (they remain on the connector-native staging
# model). Zero error-severity findings is now the pinned state; add an entry here only
# with a written [NEEDS INPUT] reason, and delete it the day the error is fixed.


@needs_enhanza
@needs_manifest
def test_enhanza_has_no_unaccepted_error_drift() -> None:
    """The state this change left the project in. A new error here is a real defect."""
    findings = checker.run(ENHANZA_SLUG, None, str(ENHANZA / "target/manifest.json"))
    errors = {
        (f.connector, f.check, f.subject)
        for f in findings
        if f.severity == checker.ERROR
    }
    unexpected = errors - ACCEPTED_ERRORS
    assert not unexpected, f"new error-severity drift: {sorted(unexpected)}"
    if _lineage.sqlglot is None:
        # Every accepted error is adapter-column drift, which needs the parser to detect.
        # Without it their absence is expected, not progress.
        return
    stale = ACCEPTED_ERRORS - errors
    assert not stale, (
        f"these accepted errors no longer occur — delete them from ACCEPTED_ERRORS "
        f"and from the CONNECTORS.md drift table: {sorted(stale)}"
    )


@needs_enhanza
def test_unknown_connector_is_rejected_with_the_known_list() -> None:
    with pytest.raises(SystemExit) as excinfo:
        checker.run(ENHANZA_SLUG, "not_a_connector", None)
    assert "fortnox" in str(excinfo.value)


# ---------------------------------------------------------------------------------------
# Alias collisions
# ---------------------------------------------------------------------------------------


def _manifest(models: list[dict]) -> dict:
    return {
        "metadata": {"project_name": "toy", "dbt_version": "1.9.9", "adapter_type": "duckdb"},
        "nodes": {
            f"model.toy.{m['name']}": {
                "resource_type": "model",
                "name": m["name"],
                "alias": m.get("alias", m["name"]),
                "schema": m.get("schema", "main"),
                "original_file_path": m.get("path", f"models/{m['name']}.sql"),
                "config": {"schema": m.get("config_schema")},
                "tags": m.get("tags", []),
            }
            for m in models
        },
        "sources": {}, "macros": {}, "exposures": {}, "metrics": {},
        "parent_map": {}, "child_map": {},
    }


def test_same_alias_in_same_schema_is_an_error() -> None:
    manifest = _manifest([
        {"name": "shopify_bi_dim_articles", "alias": "dim_articles", "config_schema": "bi"},
        {"name": "logic_bi_dim_articles", "alias": "dim_articles", "config_schema": "bi"},
    ])
    findings = checker.check_alias_collisions(manifest)
    assert len(findings) == 1
    assert findings[0].severity == checker.ERROR
    assert findings[0].check == "alias-collision"
    assert "bi.dim_articles" in findings[0].message


def test_same_alias_in_different_schemas_is_fine() -> None:
    """The intended design: the dataset separates them, not the table name."""
    manifest = _manifest([
        {"name": "shopify_bi_dim_articles", "alias": "dim_articles", "config_schema": "shopify_bi"},
        {"name": "logic_bi_dim_articles", "alias": "dim_articles", "config_schema": "logic_bi"},
    ])
    assert checker.check_alias_collisions(manifest) == []


def test_distinct_aliases_produce_no_findings() -> None:
    manifest = _manifest([
        {"name": "a", "alias": "dim_a", "config_schema": "bi"},
        {"name": "b", "alias": "dim_b", "config_schema": "bi"},
    ])
    assert checker.check_alias_collisions(manifest) == []


# ---------------------------------------------------------------------------------------
# Generic-test syntax version
# ---------------------------------------------------------------------------------------


def _toy_project(tmp_path: Path, *, require: str, schema_yml: str) -> new_connector.Conventions:
    project = tmp_path / "dbt_project"
    staging = project / "models" / "staging" / "acme"
    staging.mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        f"name: 'toy'\nmodel-paths: [\"models\"]\nrequire-dbt-version: [{require}]\n"
        f"vars:\n  is_acme_enabled: false\n",
        encoding="utf-8",
    )
    (staging / "acme_bi_dim_customers_staging.sql").write_text(
        "select * from {{ source('acme_api', 'customers') }}\n", encoding="utf-8"
    )
    (staging / "schema.yml").write_text(schema_yml, encoding="utf-8")
    (project / "models" / "sources.yml").write_text(
        "sources:\n  - name: acme_api\n    loaded_at_field: _loaded_at\n"
        "    freshness:\n      warn_after: {count: 12, period: hour}\n"
        "    tables:\n      - name: customers\n",
        encoding="utf-8",
    )
    return new_connector.Conventions(
        use_case=tmp_path, project=project, models=project / "models"
    )


ARGUMENTS_SYNTAX = """\
models:
  - name: acme_bi_dim_customers_staging
    columns:
      - name: CustomerId
        data_tests:
          - relationships:
              arguments:
                to: ref('acme_bi_dim_company')
                field: OrgId
"""

FLAT_SYNTAX = """\
models:
  - name: acme_bi_dim_customers_staging
    columns:
      - name: CustomerId
        data_tests:
          - relationships:
              to: ref('acme_bi_dim_company')
              field: OrgId
"""


def test_arguments_syntax_below_dbt_110_is_an_error(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=ARGUMENTS_SYNTAX)
    findings = checker.check_test_syntax(conv, "acme")
    assert len(findings) == 1
    assert findings[0].severity == checker.ERROR
    assert findings[0].check == "test-syntax"
    # `arguments:` is line 7 of ARGUMENTS_SYNTAX; the finding must point a reader at it.
    assert findings[0].where.endswith(":7"), findings[0].where


def test_arguments_syntax_is_fine_when_the_project_floors_at_110(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.10.0", "<2.0.0"', schema_yml=ARGUMENTS_SYNTAX)
    assert checker.check_test_syntax(conv, "acme") == []


def test_flat_syntax_is_always_fine(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=FLAT_SYNTAX)
    assert checker.check_test_syntax(conv, "acme") == []


# ---------------------------------------------------------------------------------------
# Dependency discipline and source declaration
# ---------------------------------------------------------------------------------------


def test_hardcoded_from_is_an_error(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=FLAT_SYNTAX)
    bad = conv.models / "staging" / "acme" / "acme_bi_raw_staging.sql"
    bad.write_text("select * from warehouse.raw.acme_customers\n", encoding="utf-8")
    findings = checker.check_dependency_discipline([bad], "acme", conv)
    assert len(findings) == 1
    assert findings[0].check == "hardcoded-source"
    assert findings[0].severity == checker.ERROR


def test_source_and_ref_both_satisfy_discipline(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=FLAT_SYNTAX)
    staging = conv.models / "staging" / "acme"
    a = staging / "a.sql"
    a.write_text("select * from {{ source('acme_api', 'customers') }}\n", encoding="utf-8")
    b = staging / "b.sql"
    b.write_text("select * from {{ ref('a') }}\n", encoding="utf-8")
    assert checker.check_dependency_discipline([a, b], "acme", conv) == []


def test_missing_source_block_is_an_error(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=FLAT_SYNTAX)
    (conv.models / "sources.yml").write_text("sources: []\n", encoding="utf-8")
    findings = checker.check_sources_declared(conv, "acme")
    assert [f.check for f in findings] == ["no-source-block"]


def test_missing_enable_var_is_an_error(tmp_path: Path) -> None:
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=FLAT_SYNTAX)
    findings = checker.check_enable_var(conv, "other")
    assert [f.check for f in findings] == ["no-enable-var"]
    assert checker.check_enable_var(conv, "acme") == []


def test_enable_var_is_not_demanded_of_a_project_that_gates_nothing(tmp_path: Path) -> None:
    """Connector gating is one project's architecture, not a universal rule.

    A single-source use-case with no tenancy has no use for `is_<src>_enabled`, and reporting
    its absence there marks an unbuilt feature as a defect. The check exists to catch the
    project that gates its *other* connectors and forgot this one — so it is conditional on
    the project gating anything at all.
    """
    conv = _toy_project(tmp_path, require='">=1.9.0", "<2.0.0"', schema_yml=FLAT_SYNTAX)
    (conv.project / "dbt_project.yml").write_text(
        "name: 'toy'\nmodel-paths: [\"models\"]\n", encoding="utf-8"
    )
    assert checker.check_enable_var(conv, "acme") == []
    assert checker.check_enable_var(conv, "other") == []


# ---------------------------------------------------------------------------------------
# Naming, across both convention shapes
# ---------------------------------------------------------------------------------------


def _naming_conv(tmp_path: Path, **overrides) -> new_connector.Conventions:
    project = tmp_path / "dbt_project"
    (project / "models" / "staging" / "shopify").mkdir(parents=True)
    conv = new_connector.Conventions(
        use_case=tmp_path, project=project, models=project / "models"
    )
    for key, value in overrides.items():
        setattr(conv, key, value)
    return conv


def test_naming_accepts_a_prefix_style_convention(tmp_path: Path) -> None:
    """`stg_shopify__orders` satisfies `stg_<src>__<table>` and must not be reported.

    A prefix-style project carries the connector in `model_prefix` and has no staging suffix
    at all. The check tested `endswith(staging_suffix)`, which is vacuously false against an
    empty suffix — so every model in such a project failed a convention it was already
    following, and the message named `shopifyNone<concept>` as the alternative.
    """
    conv = _naming_conv(
        tmp_path, model_prefix="stg_", staging_infix="__", staging_suffix="", adapter_infix=None
    )
    staging = conv.models / "staging" / "shopify"
    files = []
    for name in ("stg_shopify__orders", "stg_shopify__order_lines", "stg_shopify__customers"):
        path = staging / f"{name}.sql"
        path.write_text("select 1\n", encoding="utf-8")
        files.append(path)
    assert checker.check_naming(files, "shopify", conv) == []


def test_naming_still_rejects_a_model_outside_the_convention(tmp_path: Path) -> None:
    conv = _naming_conv(
        tmp_path, model_prefix="stg_", staging_infix="__", staging_suffix="", adapter_infix=None
    )
    bad = conv.models / "staging" / "shopify" / "shopify_orders_v2.sql"
    bad.write_text("select 1\n", encoding="utf-8")
    findings = checker.check_naming([bad], "shopify", conv)
    assert [f.check for f in findings] == ["naming"]
    # With no adapter convention, the message must not invent one.
    assert "None" not in findings[0].message, findings[0].message


def test_naming_accepts_a_suffix_style_convention(tmp_path: Path) -> None:
    conv = _naming_conv(
        tmp_path, model_prefix="", staging_infix="_bi_", staging_suffix="_staging",
        adapter_infix="_erp_bi_",
    )
    staging = conv.models / "staging" / "shopify"
    good = staging / "shopify_bi_dim_customers_staging.sql"
    good.write_text("select 1\n", encoding="utf-8")
    adapter = staging / "shopify_erp_bi_dim_customers.sql"
    adapter.write_text("select 1\n", encoding="utf-8")
    assert checker.check_naming([good, adapter], "shopify", conv) == []


# ---------------------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------------------


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=180
    )


@needs_enhanza
@needs_manifest
@needs_sqlglot
def test_check_flag_gates_on_error_findings() -> None:
    """`--check` exits with the error state, whatever it currently is.

    Keyed to ACCEPTED_ERRORS so this test and that registry cannot disagree: while a
    documented `[NEEDS INPUT]` error stood (the Favrit article number, until the adapter
    was conformed), the expectation was 1; with the registry empty it is 0, and a regression
    that reintroduces an error fails here as well as in the drift test.
    """
    result = _run([
        "--use-case", ENHANZA_SLUG,
        "--manifest", str(ENHANZA / "target/manifest.json"),
        "--check",
    ])
    expected = 1 if ACCEPTED_ERRORS else 0
    assert result.returncode == expected, result.stdout + result.stderr


@needs_enhanza
def test_warn_as_error_surfaces_the_open_warnings() -> None:
    """The freshness and naming warnings are real; --warn-as-error is how CI opts in."""
    result = _run(["--use-case", ENHANZA_SLUG, "--check", "--warn-as-error"])
    assert result.returncode == 1
    assert "warning(s)" in result.stdout


@needs_enhanza
def test_output_states_the_learned_conventions() -> None:
    result = _run(["--use-case", ENHANZA_SLUG])
    assert result.returncode == 0
    assert "conventions:" in result.stdout
    assert "_staging" in result.stdout


# ---------------------------------------------------------------------------------------
# Machine-readable output
# ---------------------------------------------------------------------------------------


@needs_enhanza
def test_json_format_is_a_single_parseable_document() -> None:
    result = _run(["--use-case", ENHANZA_SLUG, "--format", "json"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["use_case"] == ENHANZA_SLUG
    assert isinstance(payload["findings"], list)


@needs_enhanza
def test_json_findings_are_uniform_records() -> None:
    """TOON declares fields once, which only works if every row has the same fields."""
    payload = json.loads(_run(["--use-case", ENHANZA_SLUG, "--format", "json"]).stdout)
    keys = {tuple(sorted(f)) for f in payload["findings"]}
    assert len(keys) <= 1, f"ragged records would break the TOON header: {keys}"


@needs_enhanza
def test_check_detail_is_stated_once_not_per_finding() -> None:
    payload = json.loads(_run(["--use-case", ENHANZA_SLUG, "--format", "json"]).stdout)
    checks = {c["check"] for c in payload["checks"]}
    assert checks == {f["check"] for f in payload["findings"]}
    for finding in payload["findings"]:
        assert "message" not in finding, "the template belongs in `checks`, once"


@needs_enhanza
def test_json_format_preserves_the_check_exit_code() -> None:
    """`--check` gates CI; the format must not change whether it fails."""
    text = _run(["--use-case", ENHANZA_SLUG, "--check", "--warn-as-error"])
    js = _run(["--use-case", ENHANZA_SLUG, "--check", "--warn-as-error", "--format", "json"])
    assert text.returncode == js.returncode == 1


def test_common_prefix_cuts_only_on_a_separator() -> None:
    assert checker._common_prefix(["a/b/c.sql", "a/b/d.sql"]) == "a/b/"
    # `a/erp` and `a/erpx` share characters but not a directory.
    assert checker._common_prefix(["a/erp/c.sql", "a/erpx/d.sql"]) == "a/"
    assert checker._common_prefix(["only/one.sql"]) == ""
    assert checker._common_prefix([]) == ""


# ---------------------------------------------------------------------------------------
# Cross-model checks under a scoped run
# ---------------------------------------------------------------------------------------
#
# The question `/new-connector` has to answer is "does this connector conflict with the
# models already here". Only the manifest-backed checks can answer it, and they were
# originally skipped whenever `--connector` was passed — which is the exact invocation the
# command runs. These pin that they run, and that they stay scoped.


def _project_with_new_connector() -> dict:
    return _manifest([
        # existing
        {"name": "fortnox_bi_dim_company", "alias": "dim_company",
         "config_schema": "fortnox_bi", "path": "models/fortnox/fortnox_bi/f.sql",
         "tags": ["fortnox"]},
        {"name": "logic_bi_dim_articles", "alias": "dim_articles",
         "config_schema": "logic_bi", "path": "models/logic_bi/l.sql", "tags": ["logic"]},
        # the newcomer, landing in a dataset that already owns the concept
        {"name": "acme_bi_dim_company", "alias": "dim_company",
         "config_schema": "fortnox_bi", "path": "models/staging/acme/a.sql",
         "tags": ["acme"]},
    ])


def test_scoped_run_catches_a_collision_with_an_existing_model() -> None:
    findings = checker.check_alias_collisions(_project_with_new_connector(), "acme")
    assert len(findings) == 1
    assert findings[0].subject == "fortnox_bi.dim_company"
    assert findings[0].severity == checker.ERROR
    # The finding must name the existing model too, or it is not actionable.
    assert "models/fortnox/fortnox_bi/f.sql" in findings[0].where


def test_scoped_run_reports_the_named_connector_as_owner() -> None:
    findings = checker.check_alias_collisions(_project_with_new_connector(), "acme")
    assert findings[0].connector == "acme"


def test_scoped_run_hides_collisions_the_connector_is_not_part_of() -> None:
    manifest = _manifest([
        {"name": "a_bi_dim_x", "alias": "dim_x", "config_schema": "s",
         "path": "models/a/x.sql", "tags": ["a"]},
        {"name": "b_bi_dim_x", "alias": "dim_x", "config_schema": "s",
         "path": "models/b/x.sql", "tags": ["b"]},
    ])
    assert checker.check_alias_collisions(manifest, "acme") == []
    assert len(checker.check_alias_collisions(manifest)) == 1


def test_connector_membership_falls_back_past_tags() -> None:
    """A model with no tags is precisely the sloppily-added one this must still catch."""
    by_path = {"tags": [], "original_file_path": "models/staging/acme/x.sql", "name": "x"}
    by_name = {"tags": [], "original_file_path": "models/other/y.sql", "name": "acme_dim_y"}
    neither = {"tags": [], "original_file_path": "models/other/z.sql", "name": "z"}
    assert checker._node_belongs_to(by_path, "acme")
    assert checker._node_belongs_to(by_name, "acme")
    assert not checker._node_belongs_to(neither, "acme")


@needs_enhanza
@needs_manifest
def test_scoped_run_with_manifest_runs_cross_model_checks() -> None:
    """Regression guard: these were skipped whenever --connector was given."""
    manifest = str(ENHANZA / "target/manifest.json")
    import unittest.mock as mock
    with mock.patch.object(
        checker, "check_alias_collisions", wraps=checker.check_alias_collisions
    ) as spy:
        checker.run(ENHANZA_SLUG, "fortnox", manifest)
    assert spy.called, "a scoped run must still compare against every model"


# ---------------------------------------------------------------------------------------
# Adapter column drift
# ---------------------------------------------------------------------------------------
#
# `erp_union()` stacks one adapter per enabled source. An adapter that omits a column the
# others carry produces a union that is only wrong when two sources are enabled at once, so
# the connector's own build passes and the failure waits for a tenant with both. Found two
# real instances on first run: `visma_economic_erp_bi_dim_articles` calls a column `isActive`
# where five other adapters call it `Active`, and `favrit_erp_bi_fact_order_rows` omits
# `ArticleNumber`.

def _adapter_manifest(adapters: dict[str, str]) -> dict:
    """{source: select-list} -> a manifest of `<source>_erp_bi_dim_thing` adapters."""
    nodes = {}
    for source, select_list in adapters.items():
        name = f"{source}_erp_bi_dim_thing"
        nodes[f"model.toy.{name}"] = {
            "resource_type": "model",
            "name": name,
            "alias": name,
            "schema": f"{source}_staging",
            "original_file_path": f"models/staging/{source}/{name}.sql",
            "config": {"schema": f"{source}_staging"},
            "tags": [source],
            "raw_code": f"select {select_list} from {{{{ source('{source}_api', 't') }}}}",
            "depends_on": {"nodes": [], "macros": []},
            "columns": {},
        }
    return {
        "metadata": {"project_name": "toy", "dbt_version": "1.9.9", "adapter_type": "duckdb"},
        "nodes": nodes, "sources": {}, "macros": {}, "exposures": {}, "metrics": {},
        "parent_map": {}, "child_map": {},
    }


@needs_sqlglot
def test_an_adapter_missing_a_majority_column_is_an_error() -> None:
    manifest = _adapter_manifest({
        "alpha": "Id, Name, Active",
        "beta": "Id, Name, Active",
        "gamma": "Id, Name",
    })
    findings = checker.check_adapter_column_drift(manifest)
    assert len(findings) == 1
    assert findings[0].connector == "gamma"
    assert findings[0].severity == checker.ERROR
    assert "Active" in findings[0].message


@needs_sqlglot
def test_adapters_that_agree_produce_nothing() -> None:
    manifest = _adapter_manifest({
        "alpha": "Id, Name, Active",
        "beta": "Id, Name, Active",
    })
    assert checker.check_adapter_column_drift(manifest) == []


@needs_sqlglot
def test_a_likely_rename_is_named_in_the_finding() -> None:
    """The real case: `isActive` where everyone else says `Active`."""
    manifest = _adapter_manifest({
        "alpha": "Id, Active",
        "beta": "Id, Active",
        "gamma": "Id, isActive",
    })
    findings = checker.check_adapter_column_drift(manifest)
    assert len(findings) == 1
    assert "isActive" in findings[0].message
    assert "different name" in findings[0].message


@needs_sqlglot
def test_drift_is_scoped_to_the_named_connector() -> None:
    manifest = _adapter_manifest({
        "alpha": "Id, Active",
        "beta": "Id, Active",
        "gamma": "Id",
    })
    assert checker.check_adapter_column_drift(manifest, "alpha") == []
    assert len(checker.check_adapter_column_drift(manifest, "gamma")) == 1


@needs_sqlglot
def test_a_single_adapter_has_nothing_to_disagree_with() -> None:
    assert checker.check_adapter_column_drift(_adapter_manifest({"alpha": "Id, Name"})) == []


# ---------------------------------------------------------------------------------------
# check_source_columns
# ---------------------------------------------------------------------------------------


def _real_manifest():
    import json as _json

    path = (
        REPO
        / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/target/manifest.json"
    )
    if not path.is_file():
        pytest.skip("no manifest — run artifacts/refresh.sh")
    return _json.loads(path.read_text(encoding="utf-8"))


def _sqlglot_or_skip():
    import sys as _sys

    _sys.path.insert(0, str(REPO / "scripts"))
    import dbt_column_lineage as lineage_mod

    if lineage_mod.sqlglot is None:
        pytest.skip("sqlglot not installed")


def test_source_columns_check_is_clean_on_the_committed_project():
    """Every column staging reads is declared. This is the gate, not a smoke test."""
    _sqlglot_or_skip()

    findings = checker.check_source_columns(_real_manifest())

    assert findings == [], "\n".join(f.message for f in findings[:5])


def test_source_columns_check_fires_when_a_declared_column_disappears():
    """The project is currently clean, so without this the check could silently break."""
    import copy

    _sqlglot_or_skip()
    manifest = copy.deepcopy(_real_manifest())

    removed = None
    for node in manifest["sources"].values():
        columns = node.get("columns") or {}
        if node.get("name") == "articles" and "Active" in columns:
            del columns["Active"]
            removed = f"{node['source_name']}.{node['name']}"
            break
    assert removed, "fixture assumption broke: no source declares articles.Active"

    findings = checker.check_source_columns(manifest)

    assert findings, f"removing a column from {removed} produced no finding"
    assert all(f.check == "undeclared-source-column" for f in findings)
    assert all(f.severity == checker.ERROR for f in findings)
    assert any("Active" in f.message for f in findings)


def test_source_columns_check_scopes_to_the_named_connector():
    import copy

    _sqlglot_or_skip()
    manifest = copy.deepcopy(_real_manifest())
    for node in manifest["sources"].values():
        columns = node.get("columns") or {}
        if node.get("name") == "articles" and "Active" in columns:
            del columns["Active"]
            break

    assert checker.check_source_columns(manifest, connector="shopify") == []
    assert checker.check_source_columns(manifest) != []


def test_a_source_with_no_declared_columns_is_skipped_not_failed():
    """Most of a project has no contract the day this lands. A gate that goes red on a
    correct state gets switched off inside a week, taking the real failures with it."""
    import copy

    _sqlglot_or_skip()
    manifest = copy.deepcopy(_real_manifest())
    for node in manifest["sources"].values():
        node["columns"] = {}

    assert checker.check_source_columns(manifest) == []


def test_the_check_is_registered_in_check_detail():
    """A finding whose check has no entry renders without its explanation in JSON mode."""
    assert "undeclared-source-column" in checker.CHECK_DETAIL


def test_source_columns_check_degrades_without_sqlglot(monkeypatch):
    import sys as _sys

    _sys.path.insert(0, str(REPO / "scripts"))
    import dbt_column_lineage as lineage_mod

    monkeypatch.setattr(lineage_mod, "sqlglot", None)

    assert checker.check_source_columns(_real_manifest()) == []


def _manifest_reading(raw_code: str) -> dict:
    """A manifest with one contracted source pair and one model reading them."""
    return {
        "nodes": {
            "model.p.stg": {
                "resource_type": "model", "name": "stg", "package_name": "p",
                "tags": ["fortnox"], "raw_code": raw_code,
                "depends_on": {"nodes": ["source.p.fortnox_api.accounts",
                                         "source.p.fortnox_api.vouchers"]},
            }
        },
        "sources": {
            "source.p.fortnox_api.accounts": {
                "resource_type": "source", "source_name": "fortnox_api", "name": "accounts",
                "package_name": "p", "columns": {"Number": {"name": "Number"}},
            },
            "source.p.fortnox_api.vouchers": {
                "resource_type": "source", "source_name": "fortnox_api", "name": "vouchers",
                "package_name": "p", "columns": {"Number": {"name": "Number"}},
            },
        },
        "macros": {}, "metrics": {}, "exposures": {}, "semantic_models": {},
        "parent_map": {}, "child_map": {},
    }


def test_a_qualified_read_outside_the_contract_is_still_an_error():
    """The gate has to keep working, or the ambiguity exemption is just a way to switch it
    off. `a.Ghost` names its table, so nothing excuses it."""
    if _lineage.sqlglot is None:
        pytest.skip("needs sqlglot")
    sql = ("select a.Ghost from {{ source('fortnox_api','accounts') }} a "
           "join {{ source('fortnox_api','vouchers') }} v on v.Number = a.Number")

    findings = checker.check_source_columns(_manifest_reading(sql))

    assert [f.check for f in findings] == ["undeclared-source-column"]
    assert "Ghost" in findings[0].message


def test_an_ambiguous_read_neither_writes_a_contract_nor_fails_one():
    """The emitter refuses to declare a column it cannot attribute; this gate must refuse to
    blame a table for one, or the same weak binding fails a contract it was never allowed to
    write. `Amount` is unqualified with two tables in scope, so it belongs to exactly one of
    them and the SQL does not say which."""
    if _lineage.sqlglot is None:
        pytest.skip("needs sqlglot")
    sql = ("select Amount from {{ source('fortnox_api','accounts') }} a "
           "join {{ source('fortnox_api','vouchers') }} v on v.Number = a.Number")

    findings = checker.check_source_columns(_manifest_reading(sql))

    assert findings == [], [f.message for f in findings]
