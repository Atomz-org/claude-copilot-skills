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
    return Manifest({
        "semantic_models": {
            "semantic_model.p.orders": {
                "name": "orders",
                "description": "Order facts.",
                "depends_on": {"nodes": ["model.p.fct_orders"]},
                "measures": [
                    {"name": "order_total", "agg": "sum", "expr": "amount"},
                    {"name": "order_count", "agg": "count", "expr": "order_id"},
                    {"name": "p50", "agg": "percentile", "expr": "amount"},
                ],
                "dimensions": [
                    {"name": "status", "type": "categorical", "expr": "status"},
                    {"name": "ordered_at", "type": "time", "expr": "ordered_at"},
                    {"name": "ghost", "type": "categorical", "expr": "not_a_column"},
                ],
            },
        },
    }, "m")


def _catalog() -> dict:
    return {"nodes": {"model.p.fct_orders": {"columns": {
        "amount": {"type": "DECIMAL(18,2)"},
        "order_id": {"type": "INTEGER"},
        "status": {"type": "VARCHAR"},
        "ordered_at": {"type": "TIMESTAMP"},
    }}}}


def test_cube_types_come_from_the_catalog_or_the_part_is_skipped() -> None:
    cubes, skipped = wcs.build_cubes(_semantic_manifest(), _catalog(), "toy")
    assert list(cubes) == ["orders"]
    text = cubes["orders"]
    assert "SUM(amount)" in text and "type: DOUBLE" in text
    assert "expression: status" in text and "type: VARCHAR" in text
    assert "type: TIMESTAMP" in text  # time dimension typed from the catalog
    # percentile has no faithful single-expression projection; ghost is not a column.
    assert any("p50" in s for s in skipped)
    assert any("ghost" in s for s in skipped)
    assert "not_a_column" not in text


def test_a_semantic_model_missing_from_the_catalog_is_skipped_whole() -> None:
    cubes, skipped = wcs.build_cubes(_semantic_manifest(), {"nodes": {}}, "toy")
    assert cubes == {} and any("not in catalog.json" in s for s in skipped)


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
    payload = wcs.sync("example-order-revenue-mart", None, check=True)
    assert payload["status"] == "ok", (
        f"committed wren/ is stale: {payload.get('changed')} — run "
        f"scripts/use_case_sync.py --use-case example-order-revenue-mart --stage wren"
    )
    assert payload["models"] > 0 and payload["cubes"] > 0
