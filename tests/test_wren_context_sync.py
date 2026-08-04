"""Tests for the WrenAI bridge (scripts/wren_context_sync.py) and its sync stage.

The bridge orchestrates an *external* CLI, so what is worth pinning is not the importer's
output — upstream owns that — but the contracts this repository adds around it:

1. **Every missing input skips with the remedy named**, because the stage runs inside the
   `--all --check` CI gate and a red state on a bare runner gets the gate disabled.
2. **The run_results sanitizer is a scoped, restoring workaround.** wrenai 0.13.2 crashes
   on model-level dbt tests (external/patches/wrenai-dbt-import-columnless-tests.patch);
   the workaround must drop only the columnless rows and must restore the original file on
   any exit, or a crashed sync leaves the dbt target corrupted.
3. **Enrichment never invents.** Cube measure/dimension types come from catalog.json or the
   part is skipped and counted; empty artifacts produce no file rather than an empty one.
4. **The `wren` stage is sequenced last** so it projects the artifacts the earlier stages
   just refreshed, not the previous generation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import use_case_sync as ucs  # noqa: E402
import wren_context_sync as wcs  # noqa: E402
from _manifest import Manifest  # noqa: E402

EXAMPLE = REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart"


# ---------------------------------------------------------------------------------------
# Skips name the way out
# ---------------------------------------------------------------------------------------


def _use_case(tmp_path: Path, monkeypatch, with_project=False, with_manifest=False,
              with_catalog=False) -> str:
    slug = "toy-uc"
    root = tmp_path / "skill-packs/dbt-skills/use-cases" / slug
    root.mkdir(parents=True)
    if with_project:
        (root / "dbt_project/target").mkdir(parents=True)
    if with_manifest:
        (root / "dbt_project/target/manifest.json").write_text("{}", encoding="utf-8")
    if with_catalog:
        (root / "dbt_project/target/catalog.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(wcs, "REPO", tmp_path)
    return slug


def test_skip_without_dbt_project(tmp_path: Path, monkeypatch) -> None:
    slug = _use_case(tmp_path, monkeypatch)
    payload = wcs.sync(slug, None, check=True)
    assert payload["status"] == "skip" and "dbt_project" in payload["reason"]


def test_skip_without_manifest_names_dbt_parse(tmp_path: Path, monkeypatch) -> None:
    slug = _use_case(tmp_path, monkeypatch, with_project=True)
    payload = wcs.sync(slug, None, check=True)
    assert payload["status"] == "skip" and "dbt parse" in payload["reason"]


def test_skip_without_catalog_names_docs_generate(tmp_path: Path, monkeypatch) -> None:
    slug = _use_case(tmp_path, monkeypatch, with_project=True, with_manifest=True)
    payload = wcs.sync(slug, None, check=True)
    assert payload["status"] == "skip" and "dbt docs generate" in payload["reason"]


def test_skip_without_wren_cli_names_the_install(tmp_path: Path, monkeypatch) -> None:
    slug = _use_case(tmp_path, monkeypatch, with_project=True, with_manifest=True,
                     with_catalog=True)
    monkeypatch.setattr(wcs, "find_wren_cli", lambda: None)
    payload = wcs.sync(slug, None, check=True)
    assert payload["status"] == "skip" and "requirements.txt" in payload["reason"]


# ---------------------------------------------------------------------------------------
# The run_results sanitizer: scoped, and restoring on every exit
# ---------------------------------------------------------------------------------------


def _manifest_with_tests(tmp_path: Path) -> Manifest:
    data = {
        "nodes": {
            "test.p.column_level": {
                "resource_type": "test", "column_name": "id", "name": "not_null_id",
            },
            "test.p.model_level": {
                "resource_type": "test", "column_name": None, "name": "singular_check",
            },
        },
    }
    return Manifest(data, str(tmp_path / "manifest.json"))


def _run_results(tmp_path: Path) -> Path:
    target = tmp_path / "dbt_project/target"
    target.mkdir(parents=True, exist_ok=True)
    rr = target / "run_results.json"
    rr.write_text(json.dumps({
        "results": [
            {"unique_id": "test.p.column_level", "status": "pass"},
            {"unique_id": "test.p.model_level", "status": "pass"},
        ],
    }), encoding="utf-8")
    return rr


def test_sanitizer_hides_only_columnless_tests_and_restores(tmp_path: Path) -> None:
    rr = _run_results(tmp_path)
    original = rr.read_text(encoding="utf-8")
    man = _manifest_with_tests(tmp_path)

    with wcs._model_level_tests_hidden(tmp_path / "dbt_project", man):
        during = json.loads(rr.read_text(encoding="utf-8"))
        assert [r["unique_id"] for r in during["results"]] == ["test.p.column_level"]

    assert rr.read_text(encoding="utf-8") == original, "original was not restored"
    assert not rr.with_suffix(".json.wren-sync-orig").exists()


def test_sanitizer_restores_even_when_the_import_dies(tmp_path: Path) -> None:
    rr = _run_results(tmp_path)
    original = rr.read_text(encoding="utf-8")
    man = _manifest_with_tests(tmp_path)

    with pytest.raises(RuntimeError):
        with wcs._model_level_tests_hidden(tmp_path / "dbt_project", man):
            raise RuntimeError("import blew up")
    assert rr.read_text(encoding="utf-8") == original


def test_sanitizer_heals_a_stranded_backup_from_a_hard_kill(tmp_path: Path) -> None:
    """finally does not run on SIGKILL. A previous run killed inside the window leaves
    the sanitized copy at run_results.json and the original stranded at the backup name;
    the next entry must restore the original BEFORE reading, and must never let a fresh
    rename clobber the stranded copy."""
    rr = _run_results(tmp_path)
    original = rr.read_text(encoding="utf-8")
    backup = rr.with_suffix(".json.wren-sync-orig")
    rr.rename(backup)
    rr.write_text(json.dumps({"results": [
        {"unique_id": "test.p.column_level", "status": "pass"},
    ]}), encoding="utf-8")  # the sanitized survivor of a killed run

    man = _manifest_with_tests(tmp_path)
    with wcs._model_level_tests_hidden(tmp_path / "dbt_project", man):
        during = json.loads(rr.read_text(encoding="utf-8"))
        assert [r["unique_id"] for r in during["results"]] == ["test.p.column_level"]
    assert rr.read_text(encoding="utf-8") == original, "stranded original was not healed"
    assert not backup.exists()


def test_sanitizer_is_a_no_op_when_nothing_is_columnless(tmp_path: Path) -> None:
    rr = _run_results(tmp_path)
    man = Manifest({"nodes": {
        "test.p.column_level": {"resource_type": "test", "column_name": "id"},
    }}, "m")
    before_stat = rr.stat().st_mtime_ns
    with wcs._model_level_tests_hidden(tmp_path / "dbt_project", man):
        assert rr.stat().st_mtime_ns == before_stat, "file was rewritten needlessly"


# ---------------------------------------------------------------------------------------
# Enrichment never invents
# ---------------------------------------------------------------------------------------


def _semantic_manifest() -> Manifest:
    """A miniature but complete semantic layer: two semantic models joined by an
    entity, one metric of every compilable type, a saved query, and a time spine —
    the same shapes the example use-case exercises end to end."""
    flt = lambda tmpl: {"where_filters": [{"where_sql_template": tmpl}]}  # noqa: E731
    return Manifest({
        "nodes": {
            "model.p.fct_orders": {"resource_type": "model", "name": "fct_orders"},
            "model.p.dim_customers": {"resource_type": "model", "name": "dim_customers"},
            "model.p.spine": {
                "resource_type": "model", "name": "spine",
                "time_spine": {"standard_granularity_column": "date_day"},
            },
        },
        "semantic_models": {
            "semantic_model.p.orders": {
                "name": "orders",
                "description": "Order facts.",
                "defaults": {"agg_time_dimension": "ordered_at"},
                "depends_on": {"nodes": ["model.p.fct_orders"]},
                "entities": [
                    {"name": "order", "type": "primary", "expr": "order_id"},
                    {"name": "customer", "type": "foreign", "expr": "customer_id"},
                ],
                "measures": [
                    {"name": "order_total", "agg": "sum", "expr": "amount",
                     "join_to_timespine": True, "fill_nulls_with": 0},
                    {"name": "order_count", "agg": "count", "expr": "order_id"},
                    {"name": "p50", "agg": "percentile", "expr": "amount"},
                ],
                "dimensions": [
                    {"name": "status", "type": "categorical", "expr": "status"},
                    {"name": "ordered_at", "type": "time",
                     "type_params": {"time_granularity": "day"}},
                ],
            },
            "semantic_model.p.customers": {
                "name": "customers",
                "defaults": {"agg_time_dimension": "first_seen_at"},
                "depends_on": {"nodes": ["model.p.dim_customers"]},
                "entities": [{"name": "customer", "type": "primary", "expr": "customer_id"}],
                "measures": [{"name": "customer_count", "agg": "count", "expr": "customer_id"}],
                "dimensions": [
                    {"name": "region", "type": "categorical"},
                    {"name": "first_seen_at", "type": "time",
                     "type_params": {"time_granularity": "day"}},
                ],
            },
        },
        "metrics": {
            "metric.p.revenue": {
                "name": "revenue", "type": "simple",
                "description": "Gross revenue, excluding cancelled.",
                "type_params": {"measure": {"name": "order_total",
                                            "join_to_timespine": True,
                                            "fill_nulls_with": 0}},
                "filter": flt("{{ Dimension('order__status') }} != 'cancelled'"),
            },
            "metric.p.orders_n": {
                "name": "orders_n", "type": "simple",
                "type_params": {"measure": {"name": "order_count"}},
            },
            "metric.p.emea_share": {
                "name": "emea_share", "type": "ratio",
                "type_params": {
                    "numerator": {"name": "revenue",
                                  "filter": flt("{{ Dimension('customer__region') }} = 'EMEA'")},
                    "denominator": {"name": "revenue"},
                },
            },
            "metric.p.growth": {
                "name": "growth", "type": "derived",
                "type_params": {
                    "expr": "(revenue - prev) * 100.0 / nullif(prev, 0)",
                    "metrics": [
                        {"name": "revenue"},
                        {"name": "revenue", "alias": "prev",
                         "offset_window": {"count": 1, "granularity": "month"}},
                    ],
                },
            },
            "metric.p.trailing": {
                "name": "trailing", "type": "cumulative",
                "type_params": {
                    "measure": {"name": "order_total"},
                    "cumulative_type_params": {"window": {"count": 28, "granularity": "day"}},
                },
            },
            "metric.p.mtd": {
                "name": "mtd", "type": "cumulative",
                "type_params": {
                    "measure": {"name": "order_total"},
                    "cumulative_type_params": {"grain_to_date": "month"},
                },
            },
            "metric.p.conversions": {
                "name": "conversions", "type": "conversion",
                "type_params": {},
            },
            "metric.p.fct_orders": {  # name collides with a model
                "name": "fct_orders", "type": "simple",
                "type_params": {"measure": {"name": "order_count"}},
            },
        },
        "saved_queries": {
            "saved_query.p.weekly": {
                "name": "weekly",
                "query_params": {
                    "metrics": ["revenue", "emea_share"],
                    "group_by": ["TimeDimension('metric_time', 'week')",
                                 "Dimension('customer__region')"],
                    "where": flt("{{ Dimension('customer__region') }} is not null"),
                },
            },
        },
    }, "m")


def _catalog() -> dict:
    return {"nodes": {
        "model.p.fct_orders": {"columns": {
            "amount": {"type": "DECIMAL(18, 2)"},
            "order_id": {"type": "INTEGER"},
            "customer_id": {"type": "INTEGER"},
            "status": {"type": "VARCHAR"},
            "ordered_at": {"type": "TIMESTAMP"},
        }},
        "model.p.dim_customers": {"columns": {
            "customer_id": {"type": "INTEGER"},
            "region": {"type": "VARCHAR"},
            "first_seen_at": {"type": "TIMESTAMP"},
        }},
        "model.p.spine": {"columns": {"date_day": {"type": "DATE"}}},
    }}


def _views() -> tuple[dict, list]:
    return wcs.build_metric_views(_semantic_manifest(), _catalog(), "toy")


def test_every_compilable_metric_type_becomes_a_view() -> None:
    views, skipped = _views()
    assert sorted(views) == [
        "emea_share", "growth", "mtd", "orders_n", "revenue", "trailing", "weekly",
    ]
    # Unsupported type and model-name collision are skips, never approximations.
    assert any("conversions" in s and "conversion" in s for s in skipped)
    assert any("fct_orders" in s and "model name" in s for s in skipped)


def test_simple_metric_carries_filter_cast_and_timespine_fill() -> None:
    views, _ = _views()
    text = views["revenue"]
    # The metric's filter is IN the SQL — the 4.4% cube divergence was this filter
    # existing only as prose.
    assert "!= 'cancelled'" in text
    # Parameterized DECIMAL casts to its own catalog type (space stripped), because
    # wren-core registers it as Utf8 when planning a view statement.
    assert "CAST(fct_orders.amount AS DECIMAL(18,2))" in text
    # join_to_timespine + fill_nulls_with compile to the spine join and COALESCE,
    # bounded to the observed range.
    assert "FROM spine" in text and "COALESCE(base.revenue, 0)" in text
    assert "BETWEEN (SELECT MIN(metric_time)" in text
    assert "metric_type: simple" in text and "source: dbt_metric" in text


def test_ratio_filters_the_numerator_leg_only() -> None:
    views, _ = _views()
    text = views["emea_share"]
    num = text[text.index("num AS"):text.index("den AS")]
    den = text[text.index("den AS"):]
    assert "= 'EMEA'" in num and "LEFT JOIN dim_customers" in num
    assert "= 'EMEA'" not in den and "JOIN dim_customers" not in den
    # A group with no numerator rows is 0, not a vanished row.
    assert "COALESCE(num.num, 0)" in text and "LEFT JOIN num" in text


def test_dimension_joins_are_left_outer_like_metricflow() -> None:
    """An INNER join silently dropped base rows with NULL/unmatched foreign keys —
    measured: 15 guest-checkout orders and $9,197.66 of revenue vanishing from any
    foreign-dimension cut. MetricFlow joins dimension sources LEFT OUTER."""
    views, _ = _views()
    assert "LEFT JOIN dim_customers" in views["weekly"]
    assert "\n  JOIN dim_customers" not in views["weekly"]


def test_ratio_leg_offsets_skip_instead_of_compiling_the_wrong_metric() -> None:
    man = _semantic_manifest()
    man.metrics["metric.p.rev_over_prior"] = {
        "name": "rev_over_prior", "type": "ratio",
        "type_params": {
            "numerator": {"name": "revenue"},
            "denominator": {"name": "revenue",
                            "offset_window": {"count": 1, "granularity": "month"}},
        },
    }
    views, skipped = wcs.build_metric_views(man, _catalog(), "toy")
    assert "rev_over_prior" not in views, (
        "dropping the offset compiles revenue/revenue == 1.0 — a different metric")
    assert any("rev_over_prior" in s and "offset" in s for s in skipped)


def test_derived_offset_to_grain_and_mixed_granularities_skip() -> None:
    man = _semantic_manifest()
    man.metrics["metric.p.mtd_delta"] = {
        "name": "mtd_delta", "type": "derived",
        "type_params": {
            "expr": "revenue - month_start",
            "metrics": [{"name": "revenue"},
                        {"name": "revenue", "alias": "month_start",
                         "offset_to_grain": "month"}],
        },
    }
    man.metrics["metric.p.wow_mom"] = {
        "name": "wow_mom", "type": "derived",
        "type_params": {
            "expr": "wow - mom",
            "metrics": [
                {"name": "revenue", "alias": "wow",
                 "offset_window": {"count": 7, "granularity": "day"}},
                {"name": "revenue", "alias": "mom",
                 "offset_window": {"count": 1, "granularity": "month"}},
            ],
        },
    }
    views, skipped = wcs.build_metric_views(man, _catalog(), "toy")
    assert "mtd_delta" not in views and "wow_mom" not in views
    assert any("mtd_delta" in s and "offset_to_grain" in s for s in skipped)
    # Month-truncated times shifted by 7 days match nothing on an equality join:
    # the leg would be NULL everywhere while the view validates clean.
    assert any("wow_mom" in s and "granularities" in s for s in skipped)


def test_cumulative_over_non_additive_aggs_skips() -> None:
    man = _semantic_manifest()
    man.metrics["metric.p.active_28d"] = {
        "name": "active_28d", "type": "cumulative",
        "type_params": {
            "measure": {"name": "actives"},
            "cumulative_type_params": {"window": {"count": 28, "granularity": "day"}},
        },
    }
    sm = man.semantic_models["semantic_model.p.orders"]
    sm["measures"].append({"name": "actives", "agg": "count_distinct",
                           "expr": "customer_id"})
    views, skipped = wcs.build_metric_views(man, _catalog(), "toy")
    assert "active_28d" not in views, (
        "SUM over daily COUNT(DISTINCT) counts a customer once per active day")
    assert any("active_28d" in s and "count_distinct" in s for s in skipped)


def test_derived_offset_shifts_the_offset_leg_forward() -> None:
    views, _ = _views()
    text = views["growth"]
    assert "INTERVAL '1 month'" in text
    # The formula is verbatim — never re-derived.
    assert "(revenue - prev) * 100.0 / nullif(prev, 0)" in text
    # Offset input compiles at the offset's grain.
    assert "date_trunc('month'" in text and "grain: month" in text


def test_cumulative_compiles_window_and_grain_to_date() -> None:
    views, _ = _views()
    assert "INTERVAL '28 day'" in views["trailing"]
    assert "date_trunc('month', spine.metric_time)" in views["mtd"]
    for name in ("trailing", "mtd"):
        assert "FROM spine LEFT JOIN daily" in views[name]


def test_cumulative_without_a_time_spine_is_skipped_not_guessed() -> None:
    man = _semantic_manifest()
    del man.nodes["model.p.spine"]
    views, skipped = wcs.build_metric_views(man, _catalog(), "toy")
    assert "trailing" not in views and "mtd" not in views
    assert any("time spine" in s for s in skipped)


def test_saved_query_joins_metric_ctes_on_the_full_group_key() -> None:
    views, _ = _views()
    text = views["weekly"]
    assert "date_trunc('week'" in text
    assert "region" in text and "is not null" in text
    # Null-safe join on every group key: a NULL dimension value must still align.
    assert "IS NOT DISTINCT FROM" in text
    assert "metric_type: saved_query" in text


def test_a_semantic_model_missing_from_the_catalog_is_skipped_whole() -> None:
    views, skipped = wcs.build_metric_views(_semantic_manifest(), {"nodes": {}}, "toy")
    assert views == {} and any("not in catalog.json" in s for s in skipped)


def test_empty_artifacts_produce_no_enrichment_file() -> None:
    assert wcs.concepts_markdown({}, "toy") is None
    assert wcs.contracts_markdown({"contracts": []}, "toy") is None
    assert wcs.drift_markdown({"drift": []}, "toy") is None
    assert wcs.metrics_markdown(Manifest({}, "m"), "toy") is None


def test_enrichment_files_carry_the_generated_header() -> None:
    md = wcs.metrics_markdown(Manifest({"metrics": {
        "metric.p.revenue": {"name": "revenue", "type": "simple",
                             "description": "Gross revenue."},
    }}, "m"), "toy")
    assert md is not None
    assert "Generated by scripts/wren_context_sync.py" in md
    assert "--use-case toy --stage wren" in md


def test_orphaned_generated_files_are_deleted_and_hand_authored_kept(tmp_path: Path) -> None:
    """A cube whose semantic model was removed must not survive in the committed tree
    with --check green; a hand-authored knowledge file must never be touched."""
    scratch, target = tmp_path / "scratch", tmp_path / "wren"
    (scratch / "models/kept").mkdir(parents=True)
    (scratch / "models/kept/metadata.yml").write_text("name: kept\n", encoding="utf-8")
    (target / "models/kept").mkdir(parents=True)
    (target / "models/kept/metadata.yml").write_text("name: kept\n", encoding="utf-8")
    (target / "cubes/orphan").mkdir(parents=True)
    (target / "cubes/orphan/metadata.yml").write_text(
        "name: orphan\nproperties:\n  source: dbt_semantic_model\n", encoding="utf-8")
    (target / "views/old_metric").mkdir(parents=True)
    (target / "views/old_metric/metadata.yml").write_text(
        "name: old_metric\nstatement: SELECT 1\nproperties:\n  source: dbt_metric\n",
        encoding="utf-8")
    (target / "views/hand_authored").mkdir(parents=True)
    hand_view = target / "views/hand_authored/metadata.yml"
    hand_view.write_text("name: hand_authored\nstatement: SELECT 2\n", encoding="utf-8")
    (target / "knowledge/rules").mkdir(parents=True)
    hand = target / "knowledge/rules/tribal-knowledge.md"
    hand.write_text("# Never sum refunds twice\n", encoding="utf-8")

    changed, deleted, stale = wcs.diff_and_sync(scratch, target, check=True)
    assert deleted == ["cubes/orphan/metadata.yml", "views/old_metric/metadata.yml"]
    assert stale == ["knowledge/rules/tribal-knowledge.md",
                     "views/hand_authored/metadata.yml"]
    assert (target / "cubes/orphan/metadata.yml").exists(), "--check must write nothing"

    changed, deleted, stale = wcs.diff_and_sync(scratch, target, check=False)
    assert not (target / "cubes/orphan/metadata.yml").exists(), "orphan not deleted on sync"
    assert not (target / "views/old_metric/metadata.yml").exists(), (
        "a renamed metric's generated view must not survive")
    assert hand_view.exists(), "hand-authored view was touched"
    assert hand.exists(), "hand-authored file was touched"


def test_a_foreign_manifest_override_skips_rather_than_splitting_generations(
        tmp_path: Path, monkeypatch) -> None:
    slug = _use_case(tmp_path, monkeypatch, with_project=True, with_manifest=True,
                     with_catalog=True)
    other = tmp_path / "elsewhere/manifest.json"
    other.parent.mkdir(parents=True)
    other.write_text("{}", encoding="utf-8")
    payload = wcs.sync(slug, str(other), check=True)
    assert payload["status"] == "skip" and "target" in payload["reason"]


# ---------------------------------------------------------------------------------------
# Stage wiring
# ---------------------------------------------------------------------------------------


def test_wren_stage_runs_last(monkeypatch) -> None:
    """Enrichment reads index.json and column-memory.json; running before the stages that
    regenerate them would project the previous generation."""
    order: list[str] = []

    def record(name):
        return lambda *a, **k: order.append(name) or ucs.Stage(name, ucs.OK)

    for stage in ("stage_ontology", "stage_columns", "stage_seeds",
                  "stage_graph", "stage_alignment", "stage_wren"):
        monkeypatch.setattr(ucs, stage, record(stage.removeprefix("stage_")))
    ucs.sync("enhanza-analytics", check=True, manifest_arg=None)
    assert order[-1] == "wren" and "columns" in order


def test_wren_stage_maps_skip_payload(monkeypatch, tmp_path: Path) -> None:
    class Proc:
        returncode = 0
        stdout = '{"use_case": "x", "status": "skip", "reason": "no catalog.json — dbt docs generate against the local target"}\n'
        stderr = ""

    monkeypatch.setattr(ucs.subprocess, "run", lambda *a, **k: Proc())
    stage = ucs.stage_wren(tmp_path, "x", None, check=True)
    assert stage.status == ucs.SKIP and "dbt docs generate" in stage.detail


# ---------------------------------------------------------------------------------------
# Alias collisions — multi-connector projects must import, with binding untouched
# ---------------------------------------------------------------------------------------


def _model_node(name: str, alias: str, package: str = "p") -> dict:
    return {"resource_type": "model", "name": name, "alias": alias,
            "package_name": package, "config": {}}


def test_colliding_aliases_rename_to_node_names() -> None:
    models = {
        "model.a.fortnox_bi_dim_accounts": _model_node("fortnox_bi_dim_accounts", "dim_accounts"),
        "model.a.tripletex_bi_dim_accounts": _model_node("tripletex_bi_dim_accounts", "dim_accounts"),
        "model.a.unrelated": _model_node("unrelated", "unrelated"),
    }
    renames = wcs._unique_wren_names(models)
    assert renames == {
        "model.a.fortnox_bi_dim_accounts": "fortnox_bi_dim_accounts",
        "model.a.tripletex_bi_dim_accounts": "tripletex_bi_dim_accounts",
    }, "colliding aliases fall back to dbt names; untouched nodes stay out of the map"


def test_second_order_collisions_escalate_until_unique() -> None:
    """Renaming an alias-holder to its node name can itself collide with another
    node's alias (measured: shopify_bi_dim_articles). The escalation chain
    alias -> name -> package_name -> unique_id must land every node on a unique
    final name, deterministically."""
    models = {
        "model.a.a_first": _model_node("a_first", "shopify_bi_dim_articles"),
        "model.a.shopify_bi_dim_articles": _model_node("shopify_bi_dim_articles",
                                                       "dim_articles", package="shop"),
        "model.a.z_other": _model_node("z_other", "dim_articles"),
    }
    renames = wcs._unique_wren_names(models)
    final = {uid: renames.get(uid, n.get("alias") or n["name"])
             for uid, n in models.items()}
    assert len(set(final.values())) == len(models), f"names still collide: {final}"
    # The node whose own name was already claimed escalated past it.
    assert final["model.a.shopify_bi_dim_articles"] == "shop_shopify_bi_dim_articles"
    assert wcs._unique_wren_names(models) == renames, "must be deterministic"


def test_alias_sanitizer_pins_identifier_and_restores(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    data = {"nodes": {
        "model.a.x_dim": {**_model_node("x_dim", "dim"), "schema": "x"},
        "model.a.y_dim": {**_model_node("y_dim", "dim"), "schema": "y"},
    }}
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    original = manifest_path.read_bytes()
    man = Manifest(data, "m")
    with wcs._colliding_aliases_disambiguated(manifest_path, man):
        during = json.loads(manifest_path.read_text(encoding="utf-8"))
        for uid, name in (("model.a.x_dim", "x_dim"), ("model.a.y_dim", "y_dim")):
            node = during["nodes"][uid]
            assert node["alias"] == name, "the importer must see a unique alias"
            assert node["identifier"] == "dim", (
                "identifier outranks alias in the table chain — the physical "
                "relation must not move")
    assert manifest_path.read_bytes() == original, "manifest restored byte-identical"


def test_alias_sanitizer_is_a_no_op_without_collisions(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    data = {"nodes": {"model.a.solo": _model_node("solo", "solo")}}
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    before = manifest_path.stat().st_mtime_ns
    with wcs._colliding_aliases_disambiguated(manifest_path, Manifest(data, "m")):
        assert manifest_path.stat().st_mtime_ns == before, "file rewritten needlessly"


# ---------------------------------------------------------------------------------------
# Crash healing — restore the same generation, never clobber newer work
# ---------------------------------------------------------------------------------------


def _artifact(generated_at: str, marker: str) -> str:
    return json.dumps({"metadata": {"generated_at": generated_at}, "which": marker})


def test_heal_restores_the_original_over_its_own_sanitized_copy(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    backup = tmp_path / "manifest.json.wren-sync-alias-orig"
    backup.write_text(_artifact("2026-08-04T10:00:00Z", "original"), encoding="utf-8")
    target.write_text(_artifact("2026-08-04T10:00:00Z", "sanitized"), encoding="utf-8")
    wcs._restore_or_discard(backup, target)
    assert json.loads(target.read_text(encoding="utf-8"))["which"] == "original"
    assert not backup.exists()


def test_heal_never_clobbers_an_artifact_regenerated_after_the_crash(tmp_path: Path) -> None:
    """Measured failure: SIGKILL strands the backup, the user re-parses, and the old
    heal silently replaced the FRESH manifest with the pre-crash one — the sync then
    regenerated from models that no longer exist while reporting success."""
    target = tmp_path / "manifest.json"
    backup = tmp_path / "manifest.json.wren-sync-alias-orig"
    backup.write_text(_artifact("2026-08-04T10:00:00Z", "stale"), encoding="utf-8")
    target.write_text(_artifact("2026-08-04T11:30:00Z", "fresh"), encoding="utf-8")
    wcs._restore_or_discard(backup, target)
    assert json.loads(target.read_text(encoding="utf-8"))["which"] == "fresh"
    assert not backup.exists(), "the stale backup must be discarded, not kept armed"


def test_heal_recovers_a_truncated_target_from_the_backup(tmp_path: Path) -> None:
    """A kill mid-write leaves invalid JSON at the target; the loader used to die on
    it before any heal could run, with the pristine backup sitting beside it."""
    target = tmp_path / "manifest.json"
    backup = tmp_path / "manifest.json.wren-sync-alias-orig"
    backup.write_text(_artifact("2026-08-04T10:00:00Z", "original"), encoding="utf-8")
    target.write_text('{"metadata": {"gen', encoding="utf-8")  # truncated write
    wcs._restore_or_discard(backup, target)
    assert json.loads(target.read_text(encoding="utf-8"))["which"] == "original"


def test_heal_restores_when_the_target_is_missing(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    backup = tmp_path / "manifest.json.wren-sync-alias-orig"
    backup.write_text(_artifact("2026-08-04T10:00:00Z", "original"), encoding="utf-8")
    wcs._restore_or_discard(backup, target)
    assert json.loads(target.read_text(encoding="utf-8"))["which"] == "original"


def test_generate_heals_before_reading_the_manifest(tmp_path: Path) -> None:
    """Renames must come from the true original: computing them from the sanitized
    copy finds none, and the healed original then crashes the importer — the exact
    failure the sanitizer exists to prevent, once per hard kill."""
    dbt_project = tmp_path / "dbt_project"
    (dbt_project / "target").mkdir(parents=True)
    manifest_path = dbt_project / "target" / "manifest.json"
    original = {"metadata": {"generated_at": "t0"}, "nodes": {
        "model.a.x_dim": {**_model_node("x_dim", "dim"), "schema": "x"},
        "model.a.y_dim": {**_model_node("y_dim", "dim"), "schema": "y"},
    }}
    sanitized = json.loads(json.dumps(original))
    for uid in sanitized["nodes"]:
        node = sanitized["nodes"][uid]
        node["identifier"], node["alias"] = node["alias"], node["name"]
    # Disk state after a SIGKILL mid-import: sanitized at the manifest name,
    # original stranded at the backup name.
    manifest_path.write_text(json.dumps(sanitized), encoding="utf-8")
    manifest_path.with_suffix(".json.wren-sync-alias-orig").write_text(
        json.dumps(original), encoding="utf-8")

    wcs._heal_stranded_backups(dbt_project, manifest_path)
    healed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert healed["nodes"]["model.a.x_dim"]["alias"] == "dim", "original restored"
    man = Manifest(healed, "m")
    assert wcs._unique_wren_names({
        uid: n for uid, n in man.models().items()
    }), "renames recomputed from the original — the importer must not see collisions"


# ---------------------------------------------------------------------------------------
# MCP by flow — the sync emits a ready-to-register server, or a named remedy
# ---------------------------------------------------------------------------------------


def _wren_project(tmp_path: Path, data_source: str) -> Path:
    uc = tmp_path / "skill-packs/dbt-skills/use-cases/toy"
    (uc / "wren").mkdir(parents=True)
    (uc / "dbt_project").mkdir()
    (uc / "wren/wren_project.yml").write_text(
        f"schema_version: 5\nname: toy\ndata_source: {data_source}\n", encoding="utf-8")
    return uc


def test_mcp_config_is_live_and_credential_free_for_duckdb(tmp_path: Path) -> None:
    uc = _wren_project(tmp_path, "duckdb")
    rel, skip = wcs.write_mcp_config("/opt/venv/bin/wren", uc, "toy")
    assert skip is None and rel is not None
    cfg = json.loads((uc / "wren/mcp.json").read_text(encoding="utf-8"))
    server = cfg["mcpServers"]["wren-toy"]
    assert server["args"][:2] == ["serve", "mcp"]
    assert "--no-connect" not in server["args"], "duckdb is local — live by default"
    home = Path(server["env"]["WREN_HOME"])
    conn = json.loads((home / "connection_info.json").read_text(encoding="utf-8"))
    # The connection is a derivable local path, never a credential (rule 5 shape).
    assert conn == {"datasource": "duckdb",
                    "url": str((uc / "dbt_project").resolve()), "format": "duckdb"}


def test_mcp_config_skips_with_the_profile_remedy_for_warehouses(tmp_path: Path) -> None:
    uc = _wren_project(tmp_path, "bigquery")
    rel, skip = wcs.write_mcp_config("/opt/venv/bin/wren", uc, "toy")
    assert rel is None and "wren profile add" in skip
    assert not (uc / "wren/mcp.json").exists(), (
        "a sync flow must not conjure credentials or emit a config that half-works")


def test_migrating_off_duckdb_removes_the_stale_live_config(tmp_path: Path) -> None:
    """A previously emitted config would keep an already-registered server answering
    from the frozen local duckdb build after the project moved to a warehouse — no
    error, no staleness signal. The skip path must remove it, not just decline."""
    uc = _wren_project(tmp_path, "duckdb")
    rel, skip = wcs.write_mcp_config("/opt/venv/bin/wren", uc, "toy")
    assert rel is not None and (uc / "wren/mcp.json").exists()
    (uc / "wren/wren_project.yml").write_text(
        "schema_version: 5\nname: toy\ndata_source: bigquery\n", encoding="utf-8")
    rel, skip = wcs.write_mcp_config("/opt/venv/bin/wren", uc, "toy")
    assert rel is None and "wren profile add" in skip
    assert not (uc / "wren/mcp.json").exists(), "stale live config left behind"
    assert not (uc / "wren/.wren-home").exists(), "stale connection info left behind"


def test_derived_mcp_state_never_enters_the_diff(tmp_path: Path) -> None:
    root = tmp_path / "wren"
    (root / ".wren-home").mkdir(parents=True)
    (root / ".wren-home/connection_info.json").write_text("{}", encoding="utf-8")
    (root / "mcp.json").write_text("{}", encoding="utf-8")
    assert wcs._tree(root) == {}, "absolute-path per-clone files must not be diffed"


# ---------------------------------------------------------------------------------------
# Collection scope — the submodule must not join this repository's suite
# ---------------------------------------------------------------------------------------


def test_bare_pytest_collects_only_this_repository() -> None:
    """`python -m pytest -q` is what all six CI call sites run.

    external/WrenAI ships its own test tree, and ci.yml fetches submodules to verify the
    pin — so without a collection scope, bare pytest imports upstream's connector tests
    and fails on *their* dev dependencies (pyarrow, duckdb, orjson). That is exactly how
    the baseline job broke. scripts/test_coverage_reporter.py is the second trap: a dbt
    coverage CLI whose filename matches the test glob.
    """
    config = REPO / "pytest.ini"
    assert config.is_file(), "pytest.ini is what scopes collection; CI runs bare pytest"
    text = config.read_text(encoding="utf-8")
    assert "testpaths = tests" in text
    assert "external" in text, "the submodule's own tests must stay out of this suite"


# ---------------------------------------------------------------------------------------
# The real artifact (skips on runners without the toolchain)
# ---------------------------------------------------------------------------------------

needs_wren = pytest.mark.skipif(
    wcs.find_wren_cli() is None, reason="wren CLI not installed"
)
needs_catalog = pytest.mark.skipif(
    not (EXAMPLE / "dbt_project/target/catalog.json").exists(),
    reason="no catalog.json; run dbt docs generate in the example project",
)


@needs_wren
@needs_catalog
def test_committed_wren_project_is_current() -> None:
    """Honest scope: this gate runs where the toolchain and a generated catalog exist —
    a laptop after the demo, not a bare CI runner (which skips both marks above). The
    always-on gates for the committed artifact are the demo script and the unit tests;
    CI-side currency would require committing catalog.json and installing wrenai in CI,
    a cost/benefit call deliberately not taken here."""
    payload = wcs.sync("example-order-revenue-mart", None, check=True)
    assert payload["status"] == "ok", (
        f"committed wren/ is stale: {payload.get('changed')} — run "
        f"scripts/use_case_sync.py --use-case example-order-revenue-mart --stage wren"
    )
    assert payload["models"] > 0 and payload["views"] > 0
