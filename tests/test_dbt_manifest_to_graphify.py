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


COMMITTED_FRAGMENT = (
    REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    / "artifacts/graphify-fragment.json"
)


@needs_manifest
def test_the_committed_fragment_is_what_refresh_sh_produces() -> None:
    """The committed artifact must equal its documented regeneration, exactly.

    `artifacts/refresh.sh` writes this file *without* `--with-columns`, and says why:
    column lineage roughly quadruples it, and "installing sqlglot quadrupled a
    committed artifact overnight". Nothing gated that, so the two drifted — the
    committed file carried 3884 nodes and 3817 edges of column-level lineage while
    the documented command produced 708 and 1288.

    `8950a92 chore: merge ... resolve conflicts` is where it became permanent: its two
    parents held 4110175 and 1108903 bytes of this file, and the resolution kept the
    bloated side — a generated artifact settled by hand-merge, which is precisely what
    this repository's rules forbid. A conflict in a generated path is resolved by
    regenerating, and nothing was checking.

    The cost of no gate was 4110176 bytes committed for 1110265 bytes of content, and
    a 3 MB spurious diff on the machine of anyone who ran the documented command.

    Column lineage remains available exactly as refresh.sh describes — opt-in, at
    merge time: `dbt_manifest_to_graphify.py --manifest <path> --with-columns --merge`.
    """
    if not COMMITTED_FRAGMENT.is_file():
        pytest.skip("no committed fragment")

    expected = _fragment()
    actual = json.loads(COMMITTED_FRAGMENT.read_text(encoding="utf-8"))

    assert actual["nodes"] == expected["nodes"], (
        "committed fragment's nodes differ from `refresh.sh` output — regenerate it, "
        "never hand-merge it"
    )
    assert actual["edges"] == expected["edges"]
    assert actual["hyperedges"] == expected["hyperedges"]


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
    # First-party = the root project plus its local packages (packages/<name>), which is
    # where fortnox_start_year_filter lives after the split. Vendored macro packages
    # (dbt_utils, dbt core) must still be absent.
    first_party = ("macro.enhanza_erp_bi.", "macro.enhanza_")
    # Read through `dbt_unique_ids` rather than `dbt_unique_id`: a file defining several
    # macros has no single uid, and the invariant being checked here — nothing vendored
    # gets emitted — is a property of every macro in the file, not of one of them.
    for node in macros:
        assert "dbt_packages" not in node["source_file"]
        assert node["dbt_unique_ids"], f"{node['label']} lists no macro uids"
        for uid in node["dbt_unique_ids"]:
            assert uid.startswith(first_party), uid
    assert any(
        uid.startswith("macro.enhanza_erp_bi.")
        for n in macros
        for uid in n["dbt_unique_ids"]
    )


@needs_manifest
def test_package_models_carry_their_package_path() -> None:
    """`original_file_path` is package-relative; the node id must not pretend otherwise.

    Without the package prefix a fortnox model would claim
    `<project>/models/staging/...` — a path that no longer exists — and could collide
    with a root model at the same relative path.
    """
    fragment = _fragment()
    fortnox = [
        n for n in fragment["nodes"]
        if n.get("dbt_resource_type") == "model" and n["label"].startswith("fortnox_bi_")
    ]
    assert fortnox, "no fortnox models in the fragment"
    for node in fortnox:
        assert "/packages/fortnox/models/" in node["source_file"], node["source_file"]


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


# --- reproducibility of the committed artifact -------------------------------------------

@needs_manifest
def test_a_node_id_identifies_exactly_one_node() -> None:
    """A macro file may define several macros, and the node id is derived from the FILE
    because it has to reproduce graphify's own formula byte for byte — that is what makes
    `build_merge` upgrade the existing node instead of minting a stub beside it.

    Emitting one record per macro therefore produced several records sharing one id, and
    whichever landed last won. `macros/erp/erp_union.sql` defines `erp_union`,
    `erp_sources_for` and `erp_concept_from_model_name`, so the macro that stacks every
    connector's adapter could be labelled `erp_sources_for`, and every `calls` edge into
    any of the three resolved to whichever record had won. Measured before this: 727
    nodes under 722 ids.
    """
    fragment = _fragment()
    ids = [n["id"] for n in fragment["nodes"]]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicated, f"{len(duplicated)} node id(s) carry more than one record: {duplicated[:3]}"


@needs_manifest
def test_a_multi_macro_file_names_every_macro_it_holds() -> None:
    """The id cannot distinguish them, so the record has to. Without this the collision
    fix would read as a silent loss: three macros become one node and nothing says so."""
    fragment = _fragment()
    macros = [n for n in fragment["nodes"] if n.get("dbt_resource_type") == "macro"]
    assert macros, "no macro nodes emitted"
    assert all(n.get("dbt_macros") for n in macros), "every macro node lists its macros"
    multi = [n for n in macros if len(n["dbt_macros"]) > 1]
    for node in multi:
        assert node["dbt_macros"] == sorted(node["dbt_macros"])
        # Labelled by the file, not by an arbitrary one of its macros. That the stem
        # sometimes coincides with a macro name (erp_union.sql defines erp_union) is the
        # file being named after its principal macro, not the ambiguity being fixed.
        assert node["label"] == Path(node["source_file"]).stem
        assert node["dbt_unique_id"] is None, "one uid cannot stand for several macros"
        assert len(node["dbt_unique_ids"]) == len(node["dbt_macros"])


@needs_manifest
def test_the_emission_order_is_a_property_of_the_content() -> None:
    """The committed fragment is compared byte-for-byte against a fresh emission, so its
    order must not depend on the order dbt happened to parse in. It did: `hyperedges` was
    sorted and `nodes`/`edges` were not, so the artifact reproduced on the machine that
    wrote it and nowhere else — the test was red on every laptop and green in CI, which
    is the failure mode that gets a gate ignored rather than fixed.
    """
    fragment = _fragment()
    for key in ("nodes", "edges"):
        canonical = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in fragment[key]]
        assert canonical == sorted(canonical), f"{key} are not in canonical order"
    edges = [json.dumps(e, sort_keys=True, ensure_ascii=False) for e in fragment["edges"]]
    assert len(edges) == len(set(edges)), "identical edges are emitted more than once"
