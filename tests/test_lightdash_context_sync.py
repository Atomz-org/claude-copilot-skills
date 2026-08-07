"""scripts/lightdash_context_sync.py — the Lightdash bridge.

Mirrors the invariant structure of tests/test_wren_context_sync.py: skips name the
way out, derivation invents nothing, ownership markers decide what may be rewritten,
and the classifier's verdicts match the upstream translator it mirrors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import lightdash_context_sync as mod  # noqa: E402
from _manifest import Manifest  # noqa: E402


# ---------------------------------------------------------------------------------------
# Fixtures — synthetic manifests, the wren-suite way
# ---------------------------------------------------------------------------------------


def _model(name: str, columns=(), patch: str = "p://models/schema.yml") -> dict:
    return {
        "resource_type": "model",
        "name": name,
        "columns": {c: {"name": c} for c in columns},
        "patch_path": patch,
    }


def _rel_test(child: str, parent: str, column: str, field: str) -> dict:
    return {
        "resource_type": "test",
        "name": f"rel_{child}_{column}",
        "test_metadata": {"name": "relationships", "kwargs": {"field": field}},
        "attached_node": f"model.p.{child}",
        "column_name": column,
        "depends_on": {"nodes": [f"model.p.{child}", f"model.p.{parent}"]},
    }


def _col_test(kind: str, model: str, column: str) -> dict:
    return {
        "resource_type": "test",
        "name": f"{kind}_{model}_{column}",
        "test_metadata": {"name": kind, "kwargs": {}},
        "attached_node": f"model.p.{model}",
        "column_name": column,
        "depends_on": {"nodes": [f"model.p.{model}"]},
    }


def _manifest(nodes: dict, **top) -> Manifest:
    data = {"nodes": nodes, "metadata": {"project_name": "p"}}
    data.update(top)
    return Manifest(data)


def _joined_manifest() -> Manifest:
    nodes = {
        "model.p.fct": _model("fct", ["id", "cust_id", "email"]),
        "model.p.dim": _model("dim", ["cust_id", "email"]),
        "test.p.rel": _rel_test("fct", "dim", "cust_id", "cust_id"),
        "test.p.u1": _col_test("unique", "dim", "cust_id"),
        "test.p.n1": _col_test("not_null", "dim", "cust_id"),
        "test.p.u2": _col_test("unique", "fct", "id"),
        "test.p.n2": _col_test("not_null", "fct", "id"),
    }
    return _manifest(nodes)


# ---------------------------------------------------------------------------------------
# Skips name the way out
# ---------------------------------------------------------------------------------------


def _use_case(tmp_path, monkeypatch, slug="uc", with_project=True, with_manifest=True):
    monkeypatch.setattr(mod, "REPO", tmp_path)
    uc = tmp_path / "skill-packs/dbt-skills/use-cases" / slug
    uc.mkdir(parents=True)
    if with_project:
        (uc / "dbt_project").mkdir()
        if with_manifest:
            target = uc / "dbt_project/target"
            target.mkdir()
            (target / "manifest.json").write_text(
                json.dumps({"nodes": {}, "metadata": {"project_name": "p"}}),
                encoding="utf-8",
            )
    return uc


def test_skip_without_dbt_project(tmp_path, monkeypatch) -> None:
    _use_case(tmp_path, monkeypatch, with_project=False)
    payload = mod.sync("uc", None, check=True)
    assert payload["status"] == "skip"
    assert payload["reason"] == "no dbt_project yet"


def test_skip_without_manifest_names_dbt_parse(tmp_path, monkeypatch) -> None:
    _use_case(tmp_path, monkeypatch, with_manifest=False)
    payload = mod.sync("uc", None, check=True)
    assert payload["status"] == "skip"
    assert "dbt parse" in payload["reason"]


def test_a_foreign_manifest_skips_rather_than_splitting_generations(
    tmp_path, monkeypatch
) -> None:
    """The derivation and `lightdash compile` must read the same manifest generation."""
    _use_case(tmp_path, monkeypatch)
    foreign = tmp_path / "elsewhere/manifest.json"
    foreign.parent.mkdir()
    foreign.write_text("{}", encoding="utf-8")
    payload = mod.sync("uc", str(foreign), check=True)
    assert payload["status"] == "skip"
    assert "outside dbt_project/target/" in payload["reason"]


def test_missing_cli_skips_the_compile_gate_and_names_the_install(
    tmp_path, monkeypatch
) -> None:
    _use_case(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "find_lightdash_cli", lambda: None)
    payload = mod.sync("uc", None, check=False)
    assert payload["status"] == "synced"
    assert payload["compile"]["status"] == "skip"
    assert "npm install --prefix .lightdash-cli" in payload["compile"]["detail"]


def test_check_mode_never_runs_the_compile_gate(tmp_path, monkeypatch) -> None:
    """The currency gate is about bytes; a --check that shells out to Node is a gate
    nobody keeps in the suite."""
    _use_case(tmp_path, monkeypatch)

    def explode(*_a, **_k):
        raise AssertionError("compile must not run under --check")

    monkeypatch.setattr(mod, "run_compile", explode)
    monkeypatch.setattr(mod, "find_lightdash_cli", lambda: "/fake/lightdash")
    payload = mod.sync("uc", None, check=True)
    assert payload["compile"]["status"] == "skip"


# ---------------------------------------------------------------------------------------
# Derivation invents nothing
# ---------------------------------------------------------------------------------------


def test_joins_come_from_relationships_tests(m=None) -> None:
    joins, skipped = mod.derive_joins(_joined_manifest())
    assert skipped == []
    assert joins == {
        "fct": [
            {
                "join": "dim",
                "sql_on": "${fct.cust_id} = ${dim.cust_id}",
                "type": "left",
                "relationship": "many-to-one",
            }
        ]
    }


def test_cardinality_comes_only_from_unique_tests() -> None:
    """No unique test on the parent field -> no relationship key. Omitted, not guessed."""
    man = _joined_manifest()
    del man.nodes["test.p.u1"]
    joins, _ = mod.derive_joins(man)
    assert "relationship" not in joins["fct"][0]


def test_a_unique_fk_makes_the_join_one_to_one() -> None:
    man = _joined_manifest()
    man.nodes["test.p.u3"] = _col_test("unique", "fct", "cust_id")
    joins, _ = mod.derive_joins(man)
    assert joins["fct"][0]["relationship"] == "one-to-one"


def test_an_ambiguous_parent_is_skipped_with_the_count() -> None:
    """Two model parents on one relationships test: report, never pick one."""
    man = _joined_manifest()
    man.nodes["test.p.rel"]["depends_on"]["nodes"].append("model.p.other")
    joins, skipped = mod.derive_joins(man)
    assert joins == {}
    assert skipped and "2 model parents" in skipped[0]


def test_primary_key_requires_exactly_one_unique_not_null_column() -> None:
    man = _joined_manifest()
    keys, ambiguous = mod.derive_primary_keys(man, {"fct", "dim"})
    assert keys == {"fct": "id", "dim": "cust_id"}
    assert ambiguous == []
    # A second unique+not_null column makes the key ambiguous: reported, omitted.
    man.nodes["test.p.u4"] = _col_test("unique", "dim", "email")
    man.nodes["test.p.n4"] = _col_test("not_null", "dim", "email")
    keys, ambiguous = mod.derive_primary_keys(man, {"fct", "dim"})
    assert "dim" not in keys
    assert ambiguous and "dim" in ambiguous[0]


def test_pii_hidden_comes_only_from_direct_annotations() -> None:
    annotations = [
        {"column": "email", "pii": "direct", "definition": "Contact email."},
        {"column": "cust_id", "pii": "quasi", "definition": "Customer id."},
    ]
    meta, counts = mod.derive_column_meta(_joined_manifest(), annotations, set())
    hidden = {k for k, v in meta.items() if v.get("hidden")}
    # direct -> hidden on every model that declares the column; quasi -> untouched.
    assert hidden == {("fct", "email"), ("dim", "email")}
    assert counts["pii_hidden"] == 2
    assert not any(k[1] == "cust_id" for k in meta)


def test_no_annotations_file_hides_nothing(tmp_path, monkeypatch) -> None:
    uc = _use_case(tmp_path, monkeypatch)
    payload = mod.sync("uc", None, check=True)
    assert payload["pii_hidden"] == 0
    assert payload["annotations_present"] is False


def test_ai_hints_land_only_on_join_participants() -> None:
    annotations = [
        {"column": "cust_id", "pii": "none", "definition": "Customer id.",
         "additivity": "non_additive"},
    ]
    meta, counts = mod.derive_column_meta(
        _joined_manifest(), annotations, {"fct"}
    )
    assert meta[("fct", "cust_id")]["ai_hint"].startswith("Customer id.")
    assert "non_additive" in meta[("fct", "cust_id")]["ai_hint"]
    assert ("dim", "cust_id") not in meta  # dim is not a participant here


# ---------------------------------------------------------------------------------------
# The MetricFlow classifier mirrors the upstream translator
# ---------------------------------------------------------------------------------------


def _semantic_manifest() -> Manifest:
    return _manifest(
        {},
        semantic_models={
            "semantic_model.p.orders": {
                "name": "orders",
                "measures": [{"name": "order_total"}, {"name": "order_count"}],
                "entities": [{"name": "order", "type": "primary"}],
            }
        },
        metrics={
            "metric.p.revenue": {
                "name": "revenue", "type": "simple",
                "type_params": {"measure": {"name": "order_total"}},
                "filter": {"where_filters": [
                    {"where_sql_template": "{{ Dimension('order__status') }} != 'x'"}
                ]},
            },
            "metric.p.emea_share": {
                "name": "emea_share", "type": "ratio",
                "type_params": {
                    "numerator": {"name": "revenue", "filter": {"where_filters": [
                        {"where_sql_template": "{{ Dimension('customer__region') }} = 'EMEA'"}
                    ]}},
                    "denominator": {"name": "revenue"},
                },
            },
            "metric.p.growth": {
                "name": "growth", "type": "derived",
                "type_params": {"metrics": [
                    {"name": "revenue"},
                    {"name": "revenue", "offset_window": "1 month"},
                ]},
            },
            "metric.p.mtd": {
                "name": "mtd", "type": "cumulative",
                "type_params": {"measure": {"name": "order_total"}},
            },
        },
    )


def test_simple_with_a_same_model_filter_translates() -> None:
    translated, skipped, _ = mod.classify_metricflow(_semantic_manifest())
    assert {"name": "revenue", "type": "simple", "model": "orders"} in translated


def test_cross_model_filter_offset_and_cumulative_all_skip_with_reasons() -> None:
    _, skipped, _ = mod.classify_metricflow(_semantic_manifest())
    reasons = {s["name"]: s["reason"] for s in skipped}
    assert "customer__region" in reasons["emea_share"]
    assert "time offset" in reasons["growth"]
    assert "cumulative" in reasons["mtd"]


def test_the_classifier_agrees_with_the_real_example_manifest() -> None:
    """Pinned against what the upstream CLI printed on this manifest: 3 translated,
    4 skipped (cross-model filter, offset, cumulative x2). If this fails after a
    submodule/CLI bump, the classifier drifted from the translator it mirrors."""
    manifest_path = (
        REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart/"
        "dbt_project/target/manifest.json"
    )
    if not manifest_path.exists():
        pytest.skip("example manifest not built (dbt parse writes it)")
    man = Manifest.load(str(manifest_path))
    translated, skipped, saved = mod.classify_metricflow(man)
    assert sorted(t["name"] for t in translated) == [
        "average_order_value", "order_count", "revenue",
    ]
    assert sorted(s["name"] for s in skipped) == [
        "emea_revenue_share", "revenue_growth_mom", "revenue_mtd",
        "revenue_trailing_28d",
    ]
    assert saved == ["weekly_revenue_by_region"]


# ---------------------------------------------------------------------------------------
# YAML surgery — marker-owned, insertion-only, hand-authored left alone
# ---------------------------------------------------------------------------------------

_SCHEMA = """version: 2

models:
  - name: fct
    description: One row per thing.
    config:
      tags: [finance]
    columns:
      - name: id
        description: PK.

      - name: email
        description: Contact email.

  - name: dim
    columns:
      - name: cust_id
"""


def test_insertion_is_marker_owned_and_idempotent() -> None:
    model_meta = {"fct": {"primary_key": "id"}}
    column_meta = {("fct", "email"): {"hidden": True}}
    once, report = mod.rewrite_yaml(_SCHEMA, model_meta, column_meta)
    assert report["inserted"] == ["fct", "fct.email"]
    assert f"meta:  # {mod.MARKER}" in once
    twice, report2 = mod.rewrite_yaml(once, model_meta, column_meta)
    assert twice == once
    assert report2["inserted"] == [] and report2["replaced"] == []


def test_everything_not_owned_is_byte_identical() -> None:
    new, _ = mod.rewrite_yaml(_SCHEMA, {"fct": {"primary_key": "id"}}, {})
    original_lines = set(_SCHEMA.splitlines())
    added = [ln for ln in new.splitlines() if ln not in original_lines]
    assert all(mod.MARKER in ln or ln.strip().startswith("primary_key") for ln in added)
    removed = [ln for ln in _SCHEMA.splitlines() if ln not in new.splitlines()]
    assert removed == []


def test_hand_authored_meta_is_left_alone_and_reported() -> None:
    schema = _SCHEMA.replace(
        "  - name: dim\n", "  - name: dim\n    meta:\n      owner: finance\n"
    )
    new, report = mod.rewrite_yaml(schema, {"dim": {"primary_key": "cust_id"}}, {})
    assert new == schema
    assert report["hand_authored"] == ["dim"]


def test_meta_inside_config_counts_as_hand_authored() -> None:
    schema = _SCHEMA.replace(
        "      tags: [finance]\n", "      tags: [finance]\n      meta: {owner: x}\n"
    )
    new, report = mod.rewrite_yaml(schema, {"fct": {"primary_key": "id"}}, {})
    assert new == schema
    assert "fct" in report["hand_authored"]


def test_an_orphaned_owned_block_is_removed_on_regeneration() -> None:
    with_meta, _ = mod.rewrite_yaml(_SCHEMA, {"fct": {"primary_key": "id"}}, {})
    without, report = mod.rewrite_yaml(with_meta, {}, {})
    assert without == _SCHEMA
    assert report["removed"] == ["fct"]


def test_a_file_owned_by_another_generator_is_refused_whole(
    tmp_path, monkeypatch
) -> None:
    uc = _use_case(tmp_path, monkeypatch)
    schema = uc / "dbt_project/models/schema.yml"
    schema.parent.mkdir(parents=True)
    schema.write_text(
        "# GENERATED by scripts/ontology_to_dbt.py — do not edit.\n" + _SCHEMA,
        encoding="utf-8",
    )
    man = _joined_manifest()
    (uc / "dbt_project/target/manifest.json").write_text(
        json.dumps(man.data), encoding="utf-8"
    )
    monkeypatch.setattr(mod, "find_lightdash_cli", lambda: None)
    payload = mod.sync("uc", None, check=True)
    assert payload["refused"] and "another generator" in payload["refused"][0]["reason"]
    assert "dbt_project/models/schema.yml" not in payload["changed"]


# ---------------------------------------------------------------------------------------
# Findings from the adversarial review — each was a demonstrated defect first
# ---------------------------------------------------------------------------------------


def test_two_fks_to_one_parent_get_content_derived_aliases() -> None:
    """Role-playing dimensions: Lightdash rejects an explore joining one table twice
    unless each join carries an alias. The alias is derived from the test's own FK
    column, and sql_on must reference the alias — the compiler registers the joined
    table under `alias || table`."""
    nodes = {
        "model.p.fct": _model("fct", ["id", "ship_cid", "bill_cid"]),
        "model.p.dim": _model("dim", ["cid"]),
        "test.p.r1": _rel_test("fct", "dim", "ship_cid", "cid"),
        "test.p.r2": _rel_test("fct", "dim", "bill_cid", "cid"),
    }
    nodes["test.p.r2"]["name"] = "rel_fct_bill"
    joins, skipped = mod.derive_joins(_manifest(nodes))
    assert skipped == []
    entries = joins["fct"]
    aliases = [e["alias"] for e in entries]
    assert sorted(aliases) == ["dim_bill_cid", "dim_ship_cid"]
    for e in entries:
        assert f"${{{e['alias']}." in e["sql_on"]
    # Single-FK joins stay alias-free, so existing generated YAML does not churn.
    single, _ = mod.derive_joins(_joined_manifest())
    assert "alias" not in single["fct"][0]


def test_aliased_joins_render_the_alias_key() -> None:
    lines = mod._render_model_meta(
        "    ",
        {"joins": [{"join": "dim", "alias": "dim_ship_cid",
                    "sql_on": "${fct.ship_cid} = ${dim_ship_cid.cid}", "type": "left"}]},
    )
    text = "".join(lines)
    assert "alias: dim_ship_cid" in text


def test_test_casing_is_resolved_to_the_declared_column() -> None:
    """dbt matches test columns case-insensitively; Lightdash ${refs} do not. The
    declared casing is the model's own fact — three real explores compiled
    PARTIAL_SUCCESS on exactly this before the fix."""
    nodes = {
        "model.p.fct": _model("fct", ["Id", "StockPointId"]),
        "model.p.dim": _model("dim", ["StockPointId"]),
        "test.p.rel": _rel_test("fct", "dim", "stockPointId", "stockPointId"),
    }
    joins, _ = mod.derive_joins(_manifest(nodes))
    assert joins["fct"][0]["sql_on"] == "${fct.StockPointId} = ${dim.StockPointId}"


def test_a_trailing_comment_on_the_entry_line_does_not_hide_the_model() -> None:
    schema = _SCHEMA.replace("- name: fct\n", "- name: fct  # main mart\n")
    new, report = mod.rewrite_yaml(schema, {"fct": {"primary_key": "id"}}, {})
    assert "fct" in report["found_models"]
    assert report["inserted"] == ["fct"]


def test_a_column_zero_comment_does_not_truncate_the_model_body() -> None:
    """A commented-out block at column 0 inside a model body is annotation, not
    structure. Before the fix it ended the body AND the models section, and the
    following column's meta was silently withheld — found on the real fortnox
    schema, where CostCenterId lost its ai_hint."""
    schema = _SCHEMA.replace(
        "      - name: email\n",
        "# - name: retired_column\n#   data_tests: [unique]\n      - name: email\n",
    )
    new, report = mod.rewrite_yaml(
        schema, {}, {("fct", "email"): {"hidden": True}}
    )
    assert "fct.email" in report["found_columns"]
    assert report["inserted"] == ["fct.email"]
    assert "dim" in report["found_models"]  # the section survived the comment
    again, report2 = mod.rewrite_yaml(new, {}, {("fct", "email"): {"hidden": True}})
    assert again == new and report2["inserted"] == []


def test_zero_indent_model_lists_are_scanned() -> None:
    schema = "models:\n- name: fct\n  columns:\n    - name: id\n"
    new, report = mod.rewrite_yaml(schema, {"fct": {"primary_key": "id"}}, {})
    assert report["found_models"] == ["fct"]
    assert report["inserted"] == ["fct"]


def test_comments_after_an_owned_block_survive_regeneration() -> None:
    with_meta, _ = mod.rewrite_yaml(_SCHEMA, {"fct": {"primary_key": "id"}}, {})
    annotated = with_meta.replace(
        "      primary_key: id\n",
        "      primary_key: id\n    # reviewed 2026-08\n",
    )
    again, report = mod.rewrite_yaml(annotated, {"fct": {"primary_key": "id"}}, {})
    assert "# reviewed 2026-08" in again
    assert again == annotated


def test_desired_meta_that_lands_nowhere_is_reported_never_silent(
    tmp_path, monkeypatch
) -> None:
    """A model the manifest declares but the schema file does not carry must land in
    `unplaced`, not vanish — silence here is how a PII column stays visible."""
    uc = _use_case(tmp_path, monkeypatch)
    man = _joined_manifest()
    (uc / "dbt_project/target/manifest.json").write_text(
        json.dumps(man.data), encoding="utf-8"
    )
    schema = uc / "dbt_project/models/schema.yml"
    schema.parent.mkdir(parents=True)
    schema.write_text("version: 2\n\nmodels:\n  - name: dim\n    columns:\n      - name: cust_id\n", encoding="utf-8")
    monkeypatch.setattr(mod, "find_lightdash_cli", lambda: None)
    payload = mod.sync("uc", None, check=True)
    assert any(u.startswith("fct:") for u in payload["unplaced"]), payload["unplaced"]


def test_orphaned_blocks_are_removed_when_the_evidence_disappears(
    tmp_path, monkeypatch
) -> None:
    """Deleting the relationships test must delete the join it justified, even when
    the file no longer has any desired meta at all."""
    uc = _use_case(tmp_path, monkeypatch)
    man = _joined_manifest()
    manifest_path = uc / "dbt_project/target/manifest.json"
    manifest_path.write_text(json.dumps(man.data), encoding="utf-8")
    schema = uc / "dbt_project/models/schema.yml"
    schema.parent.mkdir(parents=True)
    schema.write_text(_SCHEMA, encoding="utf-8")
    monkeypatch.setattr(mod, "find_lightdash_cli", lambda: None)
    mod.sync("uc", None, check=False)
    assert mod.MARKER in schema.read_text(encoding="utf-8")

    for uid in ("test.p.rel", "test.p.u1", "test.p.n1", "test.p.u2", "test.p.n2"):
        del man.nodes[uid]
    manifest_path.write_text(json.dumps(man.data), encoding="utf-8")
    payload = mod.sync("uc", None, check=False)
    assert mod.MARKER not in schema.read_text(encoding="utf-8")
    assert any("schema.yml" in c for c in payload["changed"])


def test_partial_success_summaries_are_parsed_not_misread(monkeypatch) -> None:
    """The CLI adds PARTIAL_SUCCESS=y whenever an explore compiles with warnings;
    the old regex missed that form and misread pre-existing failures as `fail`."""
    out = (
        "- ERROR> legacy_model : no columns\n"
        "Compiled 3 explores, SUCCESS=1 PARTIAL_SUCCESS=1 ERRORS=1\n"
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(1, out))
    verdict = mod.run_compile("/fake/cli", Path("."), meta_models={"fct"})
    assert verdict["status"] == "unready"

    ok_out = "Compiled 8 explores, SUCCESS=5 PARTIAL_SUCCESS=3 ERRORS=0\n"
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(0, ok_out))
    verdict = mod.run_compile("/fake/cli", Path("."), meta_models=set())
    assert verdict["status"] == "ok"
    assert "3 partial" in verdict["detail"]


# ---------------------------------------------------------------------------------------
# Knowledge files
# ---------------------------------------------------------------------------------------


def test_knowledge_files_carry_the_generated_header(tmp_path, monkeypatch) -> None:
    uc = _use_case(tmp_path, monkeypatch)
    man = _joined_manifest()
    (uc / "dbt_project/target/manifest.json").write_text(
        json.dumps(man.data), encoding="utf-8"
    )
    schema = uc / "dbt_project/models/schema.yml"
    schema.parent.mkdir(parents=True)
    schema.write_text(_SCHEMA, encoding="utf-8")
    monkeypatch.setattr(mod, "find_lightdash_cli", lambda: None)
    payload = mod.sync("uc", None, check=False)
    assert payload["status"] == "synced"
    for name in ("semantic-coverage.md", "mcp.md"):
        text = (uc / "lightdash/knowledge" / name).read_text(encoding="utf-8")
        assert "Generated by scripts/lightdash_context_sync.py" in text
        assert "--stage lightdash" in text


def test_skipped_metrics_are_pointed_at_the_wren_views() -> None:
    text = mod.coverage_markdown(
        "uc",
        translated=[{"name": "revenue", "type": "simple", "model": "orders"}],
        skipped=[{"name": "mtd", "type": "cumulative", "reason": "no cumulative"}],
        saved=[], joins={}, join_skips=[],
    )
    assert "served by WrenAI" in text
    assert "`mtd` (cumulative): no cumulative" in text


def test_an_empty_semantic_surface_produces_no_coverage_file() -> None:
    assert mod.coverage_markdown("uc", [], [], [], {}, []) is None


def test_mcp_doc_names_env_vars_and_never_a_token() -> None:
    text = mod.mcp_markdown("uc")
    assert "LIGHTDASH_URL" in text and "LIGHTDASH_API_KEY" in text
    assert "ldpat_..." in text  # the format, never a value
    assert "data egress" in text


# ---------------------------------------------------------------------------------------
# The compile verdict separates caused from observed
# ---------------------------------------------------------------------------------------


class _Proc:
    def __init__(self, code: int, out: str):
        self.returncode = code
        self.stdout = out
        self.stderr = ""


def test_compile_failures_without_bridge_meta_are_unready_not_fail(monkeypatch) -> None:
    out = (
        "- ERROR> some_model : No dimensions available\n"
        "Compiled 10 explores, SUCCESS=9 ERRORS=1\n"
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(1, out))
    verdict = mod.run_compile("/fake/cli", Path("."), meta_models={"fct"})
    assert verdict["status"] == "unready"
    assert "pre-existing" in verdict["detail"]


def test_compile_failures_on_bridge_meta_fail(monkeypatch) -> None:
    out = (
        "- ERROR> fct : join reference not found\n"
        "Compiled 10 explores, SUCCESS=9 ERRORS=1\n"
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(1, out))
    verdict = mod.run_compile("/fake/cli", Path("."), meta_models={"fct"})
    assert verdict["status"] == "fail"
    assert "fct" in verdict["detail"]


def test_offline_compile_gate_passes_on_the_example() -> None:
    """The live gate, exactly as the stage runs it. Skips where the toolchain or the
    locally-built manifest is absent — unavailable is not failed."""
    cli = mod.find_lightdash_cli()
    if cli is None:
        pytest.skip("lightdash CLI not installed")
    project = (
        REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project"
    )
    if not (project / "target/manifest.json").exists():
        pytest.skip("example manifest not built (dbt parse writes it)")
    verdict = mod.run_compile(cli, project, meta_models={"fct_orders", "dim_customers"})
    assert verdict["status"] == "ok", verdict


# ---------------------------------------------------------------------------------------
# The real artifacts stay current
# ---------------------------------------------------------------------------------------


def test_the_committed_lightdash_projection_is_current() -> None:
    """The committed meta blocks and knowledge files are what a fresh sync produces.

    Runs the emitter in --check over the real example use-case; skips where the
    locally-built manifest is absent (CI has no dbt), like the wren currency test."""
    manifest_path = (
        REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart/"
        "dbt_project/target/manifest.json"
    )
    if not manifest_path.exists():
        pytest.skip("example manifest not built (dbt parse writes it)")
    payload = mod.sync("example-order-revenue-mart", None, check=True)
    assert payload["status"] == "synced"
    assert payload["changed"] == [], payload["changed"]
