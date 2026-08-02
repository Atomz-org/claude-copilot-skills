"""Tests for the dbt manifest -> graphify extraction emitter.

Three things are under test, in decreasing order of how quietly they fail:

1. **The node-ID formula.** The entire point of the emitter is that it mints the ID
   graphify's AST pass already minted for the same `.sql` file, so `build_merge` upgrades
   the existing degree-0 node instead of adding a duplicate beside it. A drift here does
   not raise — it produces a graph with two nodes per model, one carrying the edges and one
   carrying nothing, and nothing reports it. The formula is therefore pinned against IDs
   taken verbatim from a real `graphify-out/graph.json`.

2. **The coverage gate.** A connector-gated dbt project parsed with the wrong `--vars`
   yields a manifest that is internally consistent and silently partial — the one committed
   to this repository before the emitter existed held 72 of 359 models. The gate is what
   turns that into an error rather than a smaller graph.

3. **Fragment shape.** graphify rejects nothing; a malformed fragment merges and the
   damage shows up later as missing attributes. The schema in
   `~/.claude/skills/graphify/references/extraction-spec.md` is asserted directly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dbt_manifest_to_graphify as emitter  # noqa: E402

SCRIPT = REPO / "scripts" / "dbt_manifest_to_graphify.py"
GRAPH = REPO / "graphify-out" / "graph.json"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project"
EXAMPLE = REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart"


# ---------------------------------------------------------------------------------------
# The node-ID formula
# ---------------------------------------------------------------------------------------

# (repo-relative path, entity, expected id). Every expectation without an entity was copied
# out of a real graph.json built by graphify's own AST extractor — they are observations,
# not a restatement of the implementation.
KNOWN_IDS = [
    (
        "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/models/fortnox/"
        "fortnox_bi/fortnox_bi_dim_company.sql",
        "",
        "skill_packs_dbt_skills_use_cases_enhanza_analytics_dbt_project_models_fortnox_"
        "fortnox_bi_fortnox_bi_dim_company",
    ),
    (
        "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/models/staging/"
        "fortnox/fortnox_bi_dim_company_staging.sql",
        "",
        "skill_packs_dbt_skills_use_cases_enhanza_analytics_dbt_project_models_staging_"
        "fortnox_fortnox_bi_dim_company_staging",
    ),
    (
        "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/macros/"
        "categories_x_mapping/cxm_left_join.sql",
        "",
        "skill_packs_dbt_skills_use_cases_enhanza_analytics_dbt_project_macros_"
        "categories_x_mapping_cxm_left_join",
    ),
]


@pytest.mark.parametrize("rel_path,entity,expected", KNOWN_IDS)
def test_node_id_matches_graphify(rel_path: str, entity: str, expected: str) -> None:
    assert emitter.node_id(rel_path, entity) == expected


def test_node_id_appends_entity_the_same_way() -> None:
    assert emitter.node_id("a/b/c.yml", "my_source") == "a_b_c_my_source"


def test_node_id_collapses_runs_and_strips_edges() -> None:
    assert emitter.node_id("a--b/__c__.sql") == "a_b_c"


def test_node_id_is_lowercase() -> None:
    assert emitter.node_id("Models/Fortnox/DimCompany.sql") == "models_fortnox_dimcompany"


@pytest.mark.skipif(not GRAPH.exists(), reason="no graphify-out/graph.json in this clone")
@pytest.mark.skipif(
    not (ENHANZA / "target/manifest.json").exists(),
    reason="no parsed manifest; run artifacts/refresh.sh",
)
def test_every_emitted_model_merges_with_an_existing_graph_node() -> None:
    """The property the whole design rests on: upgrades, never ghosts."""
    man = emitter.Manifest.load(str(ENHANZA / "target/manifest.json"))
    fragment = emitter.build_fragment(man, ENHANZA)
    graph_ids = {n["id"] for n in json.loads(GRAPH.read_text(encoding="utf-8"))["nodes"]}
    models = [n for n in fragment["nodes"] if n.get("dbt_resource_type") == "model"]
    assert models, "no model nodes emitted"
    orphans = [n["id"] for n in models if n["id"] not in graph_ids]
    assert not orphans, (
        f"{len(orphans)}/{len(models)} model nodes would be added as duplicates rather "
        f"than merged into the node graphify already has. First: {orphans[:3]}"
    )


# ---------------------------------------------------------------------------------------
# Fragment shape
# ---------------------------------------------------------------------------------------

REQUIRED_NODE_KEYS = {
    "id", "label", "file_type", "source_file", "source_location",
    "source_url", "captured_at", "author", "contributor",
}
VALID_FILE_TYPES = {"code", "document", "paper", "image", "rationale", "concept"}


def _fragment():
    man = emitter.Manifest.load(str(ENHANZA / "target/manifest.json"))
    return emitter.build_fragment(man, ENHANZA)


needs_manifest = pytest.mark.skipif(
    not (ENHANZA / "target/manifest.json").exists(),
    reason="no parsed manifest; run artifacts/refresh.sh",
)


@needs_manifest
def test_nodes_carry_the_required_schema_keys() -> None:
    for node in _fragment()["nodes"]:
        missing = REQUIRED_NODE_KEYS - set(node)
        assert not missing, f"{node['id']} missing {missing}"
        assert node["file_type"] in VALID_FILE_TYPES


@needs_manifest
def test_every_edge_is_extracted_with_full_confidence() -> None:
    """dbt compiled the DAG. Nothing here is inferred, so nothing may claim to be."""
    for edge in _fragment()["edges"]:
        assert edge["confidence"] == "EXTRACTED"
        assert edge["confidence_score"] == 1.0
        assert edge["relation"] in ("references", "calls")


@needs_manifest
def test_edges_only_reference_emitted_nodes() -> None:
    fragment = _fragment()
    ids = {n["id"] for n in fragment["nodes"]}
    for edge in fragment["edges"]:
        assert edge["source"] in ids, f"dangling source {edge['source']}"
        assert edge["target"] in ids, f"dangling target {edge['target']}"


@needs_manifest
def test_no_self_edges() -> None:
    for edge in _fragment()["edges"]:
        assert edge["source"] != edge["target"]


@needs_manifest
def test_tests_are_attributes_not_nodes() -> None:
    """193 test nodes would bury a 359-model DAG in leaf noise."""
    fragment = _fragment()
    assert not [n for n in fragment["nodes"] if n.get("dbt_resource_type") == "test"]
    assert any(n.get("dbt_test_count", 0) > 0 for n in fragment["nodes"])


@needs_manifest
def test_only_project_macros_are_emitted() -> None:
    """dbt_utils and dbt core macros are vendored, not part of this repo."""
    fragment = _fragment()
    macros = [n for n in fragment["nodes"] if n.get("dbt_resource_type") == "macro"]
    assert macros, "no project macros emitted"
    for node in macros:
        assert "dbt_packages" not in node["source_file"]
        assert node["dbt_unique_id"].startswith("macro.enhanza_analytics.")


@needs_manifest
def test_hyperedges_group_connectors() -> None:
    fragment = _fragment()
    assert fragment["hyperedges"], "no connector hyperedges emitted"
    ids = {n["id"] for n in fragment["nodes"]}
    for hyperedge in fragment["hyperedges"]:
        assert len(hyperedge["nodes"]) >= 3
        assert set(hyperedge["nodes"]) <= ids


# ---------------------------------------------------------------------------------------
# The coverage gate
# ---------------------------------------------------------------------------------------


def _write_project(tmp_path: Path, model_names: list[str]) -> Path:
    project = tmp_path / "dbt_project"
    (project / "models").mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        "name: 'toy'\nmodel-paths: [\"models\"]\n", encoding="utf-8"
    )
    for name in model_names:
        (project / "models" / f"{name}.sql").write_text("select 1\n", encoding="utf-8")
    return project


def _write_manifest(project: Path, model_names: list[str]) -> Path:
    nodes = {
        f"model.toy.{name}": {
            "resource_type": "model",
            "name": name,
            "original_file_path": f"models/{name}.sql",
            "config": {},
            "tags": [],
            "columns": {},
            "depends_on": {"nodes": [], "macros": []},
        }
        for name in model_names
    }
    manifest = {
        "metadata": {"project_name": "toy", "dbt_version": "1.9.9", "adapter_type": "duckdb"},
        "nodes": nodes,
        "sources": {},
        "macros": {},
        "exposures": {},
        "metrics": {},
        "parent_map": {k: [] for k in nodes},
        "child_map": {},
    }
    path = project / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=120
    )


def test_partial_manifest_is_refused(tmp_path: Path) -> None:
    """The failure that motivated the gate: 72 of 359 models, and nothing said so."""
    project = _write_project(tmp_path, [f"m{i}" for i in range(10)])
    manifest = _write_manifest(project, ["m0", "m1"])
    result = _run(["--manifest", str(manifest), "--out", str(tmp_path / "f.json")])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "below the" in result.stderr
    assert not (tmp_path / "f.json").exists()


def test_partial_manifest_can_be_forced(tmp_path: Path) -> None:
    project = _write_project(tmp_path, [f"m{i}" for i in range(10)])
    manifest = _write_manifest(project, ["m0", "m1"])
    result = _run([
        "--manifest", str(manifest),
        "--out", str(tmp_path / "f.json"),
        "--no-check-coverage",
    ])
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "f.json").exists()


def test_complete_manifest_passes(tmp_path: Path) -> None:
    names = [f"m{i}" for i in range(10)]
    project = _write_project(tmp_path, names)
    manifest = _write_manifest(project, names)
    result = _run(["--manifest", str(manifest), "--out", str(tmp_path / "f.json")])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "100.0%" in result.stdout


def test_stale_manifest_entry_is_reported(tmp_path: Path) -> None:
    """A model in the manifest with no .sql behind it was deleted since the parse."""
    project = _write_project(tmp_path, ["m0", "m1"])
    manifest = _write_manifest(project, ["m0", "m1", "deleted_model"])
    result = _run(["--manifest", str(manifest), "--out", str(tmp_path / "f.json")])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deleted_model" in result.stdout
    assert "stale" in result.stdout


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    names = [f"m{i}" for i in range(4)]
    project = _write_project(tmp_path, names)
    manifest = _write_manifest(project, names)
    out = tmp_path / "f.json"
    result = _run(["--manifest", str(manifest), "--out", str(out), "--dry-run"])
    assert result.returncode == 0
    assert not out.exists()


def test_missing_manifest_fails_with_an_actionable_message(tmp_path: Path) -> None:
    result = _run(["--manifest", str(tmp_path / "nope.json")])
    assert result.returncode != 0
    assert "dbt parse" in result.stderr
