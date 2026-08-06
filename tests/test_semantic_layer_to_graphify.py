"""Tests for scripts/semantic_layer_to_graphify.py — the fourth fragment emitter.

Three invariant families, inherited from the three sibling emitters because each was
a bug there first:

1. **The merge contract.** The envelope, the nine node keys, canonical ordering, and
   intra-fragment id uniqueness — `build_merge` dedups by id and sorts by content, so
   a fragment that violates any of these merges *something*, silently.
2. **No silent stubs.** Every edge endpoint outside the fragment must be a node id
   the real graph already has; a name-rule miss makes `build_merge` mint a plausible
   ghost beside the real node and nothing errors.
3. **The claim the fragment exists for.** The `joins_to` edges must be knowledge the
   graph does NOT already have: measured at design time, 0 of the 101 (child, parent)
   FK pairs appear in `parent_map`, because a fact model does not `ref()` the dim it
   joins to. If that ever stops being true the fragment is duplicating lineage, and
   this file says so.

The relation vocabulary is a closed set, pinned exactly as `references/calls` is for
the model emitter — a new relation is a deliberate act, in this file, in the same
commit.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import semantic_layer_to_graphify as sl  # noqa: E402
from _manifest import Manifest  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
EXAMPLE = REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart"
GRAPH = REPO / "graphify-out/graph.json"

REQUIRED_NODE_KEYS = {
    "id", "label", "file_type", "source_file", "source_location",
    "source_url", "captured_at", "author", "contributor",
}

needs_enhanza = pytest.mark.skipif(
    not (ENHANZA / "dbt_project/target/manifest.json").exists(),
    reason="needs the enhanza manifest — run artifacts/refresh.sh",
)
needs_example = pytest.mark.skipif(
    not (EXAMPLE / "dbt_project/target/manifest.json").exists(),
    reason="needs the example manifest — run dbt parse there",
)


def fragment_for(use_case: Path) -> dict:
    man = Manifest.load(str(use_case / "dbt_project/target/manifest.json"))
    frag = sl.build_fragment(man, use_case / "dbt_project")
    frag.pop("_join_skipped")
    return frag


@pytest.fixture(scope="module")
def example_fragment() -> dict:
    if not (EXAMPLE / "dbt_project/target/manifest.json").exists():
        pytest.skip("needs the example manifest")
    return fragment_for(EXAMPLE)


@pytest.fixture(scope="module")
def enhanza_fragment() -> dict:
    if not (ENHANZA / "dbt_project/target/manifest.json").exists():
        pytest.skip("needs the enhanza manifest")
    return fragment_for(ENHANZA)


# --- 1. the merge contract ------------------------------------------------------------

def test_envelope_keys_are_exact(example_fragment: dict) -> None:
    assert set(example_fragment) == {
        "nodes", "edges", "hyperedges", "input_tokens", "output_tokens"
    }


def test_nodes_carry_the_required_schema_keys(example_fragment: dict) -> None:
    for node in example_fragment["nodes"]:
        assert REQUIRED_NODE_KEYS <= set(node), node["id"]
        assert node["file_type"] == "code"


def test_a_node_id_identifies_exactly_one_node(enhanza_fragment: dict) -> None:
    ids = [n["id"] for n in enhanza_fragment["nodes"]]
    assert len(ids) == len(set(ids))


def test_the_emission_order_is_a_property_of_the_content(enhanza_fragment: dict) -> None:
    for key in ("nodes", "edges"):
        records = enhanza_fragment[key]
        canon = [json.dumps(r, sort_keys=True) for r in records]
        assert canon == sorted(canon), f"{key} are not canonically ordered"
        assert len(canon) == len(set(canon)), f"duplicate {key}"


def test_every_edge_is_extracted_with_full_confidence(enhanza_fragment: dict) -> None:
    for edge in enhanza_fragment["edges"]:
        assert edge["relation"] in sl.RELATIONS, edge["relation"]
        assert edge["confidence"] == "EXTRACTED"
        assert edge["confidence_score"] == 1.0
        assert edge["source"] != edge["target"], "self-edge"


# --- 2. no silent stubs ---------------------------------------------------------------

@needs_enhanza
def test_external_endpoints_are_the_graphs_own_model_ids(enhanza_fragment: dict) -> None:
    """`joins_to` and `describes` deliberately point outside the fragment; every such
    endpoint must already exist in graph.json, or build_merge mints a silent stub."""
    if not GRAPH.exists():
        pytest.skip("no graphify-out/graph.json in this checkout")
    graph_ids = {n["id"] for n in json.loads(GRAPH.read_text())["nodes"]}
    fragment_ids = {n["id"] for n in enhanza_fragment["nodes"]}
    dangling = {
        endpoint
        for e in enhanza_fragment["edges"]
        for endpoint in (e["source"], e["target"])
        if endpoint not in fragment_ids and endpoint not in graph_ids
    }
    assert not dangling, f"would mint stub nodes: {sorted(dangling)[:5]}"


def test_internal_relations_stay_internal(enhanza_fragment: dict) -> None:
    """measures/composes/bundles connect semantic-layer nodes to each other; an
    endpoint outside the fragment there means an id formula regressed."""
    fragment_ids = {n["id"] for n in enhanza_fragment["nodes"]}
    for edge in enhanza_fragment["edges"]:
        if edge["relation"] in ("measures", "composes", "bundles"):
            assert edge["source"] in fragment_ids, edge
            assert edge["target"] in fragment_ids, edge


# --- 3. the claim the fragment exists for ---------------------------------------------

@needs_enhanza
def test_join_edges_add_only_missing_knowledge(enhanza_fragment: dict) -> None:
    """0 of the FK pairs are in parent_map — the join lives only in the test. If
    this fails, joins_to has started duplicating references edges."""
    man = Manifest.load(str(ENHANZA / "dbt_project/target/manifest.json"))
    model_ids = sl._model_ids(man, ENHANZA / "dbt_project")
    graph_id_to_uid = {gid: uid for uid, gid in model_ids.items()}
    parent_map = man.data.get("parent_map", {})
    duplicated = []
    for edge in enhanza_fragment["edges"]:
        if edge["relation"] != "joins_to":
            continue
        child_uid = graph_id_to_uid[edge["source"]]
        parent_uid = graph_id_to_uid[edge["target"]]
        if parent_uid in (parent_map.get(child_uid) or []):
            duplicated.append((child_uid, parent_uid))
    assert not duplicated, f"joins already in the DAG: {duplicated[:5]}"


@needs_enhanza
def test_join_count_matches_the_relationships_tests(enhanza_fragment: dict) -> None:
    man = Manifest.load(str(ENHANZA / "dbt_project/target/manifest.json"))
    rel_tests = sum(
        1 for n in man.nodes.values()
        if n.get("resource_type") == "test"
        and (n.get("test_metadata") or {}).get("name") == "relationships"
    )
    joins = sum(1 for e in enhanza_fragment["edges"] if e["relation"] == "joins_to")
    assert joins == rel_tests, f"{joins} joins from {rel_tests} tests — silent drops"


def test_join_type_is_derived_or_absent_never_guessed(enhanza_fragment: dict) -> None:
    for edge in enhanza_fragment["edges"]:
        if edge["relation"] == "joins_to" and "dbt_join_type" in edge:
            assert edge["dbt_join_type"] in ("one_to_one", "many_to_one")


@needs_example
def test_the_semantic_layer_nodes_carry_their_definitions(example_fragment: dict) -> None:
    """The point of the nodes: an agent reads the measure list off the node instead
    of opening _semantic_models.yml."""
    by_type: dict[str, list] = {}
    for node in example_fragment["nodes"]:
        by_type.setdefault(node["dbt_resource_type"], []).append(node)

    assert len(by_type["semantic_model"]) == 2
    orders = next(n for n in by_type["semantic_model"] if "orders" in n["label"])
    assert "order_total:sum:order_amount_usd" in orders["measures"]
    assert "customer:foreign:customer_id" in orders["entities"]

    assert len(by_type["metric"]) == 7
    revenue = next(n for n in by_type["metric"] if n["label"] == "metric: revenue")
    assert revenue["dbt_metric_type"] == "simple"
    assert "order_status" in revenue["dbt_filter"]

    ratio = next(n for n in by_type["metric"]
                 if n["dbt_metric_type"] == "ratio")
    composes = [e for e in example_fragment["edges"]
                if e["relation"] == "composes" and e["source"] == ratio["id"]]
    assert len(composes) == 2, "a ratio composes exactly its two legs"


@needs_example
def test_saved_query_id_cannot_collide_with_a_metric(example_fragment: dict) -> None:
    sq = next(n for n in example_fragment["nodes"]
              if n["dbt_resource_type"] == "saved_query")
    assert "_saved_query_" in sq["id"]


# --- CLI behaviour --------------------------------------------------------------------

def _run(*args: str):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts/semantic_layer_to_graphify.py"), *args],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )


def test_a_manifest_without_the_semantic_keys_skips_with_a_reason(tmp_path: Path) -> None:
    """Synthetic manifests omit semantic_models/saved_queries entirely; `.get()`
    everywhere, and nothing-to-emit is a state, not a failure."""
    manifest = tmp_path / "target" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(
        {"nodes": {}, "sources": {}, "metadata": {}}), encoding="utf-8")
    proc = _run("--manifest", str(manifest), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "skip"
    assert "relationships tests" in payload["reason"]


@needs_enhanza
def test_dry_run_reports_the_real_counts_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "frag.json"
    proc = _run("--manifest", str(ENHANZA / "dbt_project/target/manifest.json"),
                "--out", str(out), "--dry-run", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["joins"] == 101
    assert payload["semantic_models"] == 6
    assert payload["metrics"] == 8
    assert payload["saved_queries"] == 1
    assert not out.exists(), "--dry-run wrote the fragment"
