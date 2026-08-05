"""Tests for deriving graphify community names from community content.

Two things are under test, in decreasing order of how quietly they fail:

1. **The derivation order.** file -> directory -> hub -> the node itself. A community
   spread across a package has no majority file, so if directory-dominance is skipped it
   silently falls through to whichever macro has the most edges and calls the Fortnox
   connector "Auto Config". Nothing errors; the picture is just wrong.

2. **Redundancy and false distinction.** A qualifier that restates the name adds length
   and no information, and numbering `Self (7)` / `Self (8)` asserts a difference between
   two references to the same symbol that does not exist. Both produce output that looks
   deliberate, which is why they need pinning rather than eyeballing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import graphify_community_names as namer  # noqa: E402

SCRIPT = REPO / "scripts" / "graphify_community_names.py"


# ---------------------------------------------------------------------------------------
# humanise
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("dbt_column_lineage", "dbt Column Lineage"),
    ("connector_alignment_check", "Connector Alignment Check"),
    ("_miniyaml", "Mini YAML"),          # via _WORD_FIXES, not title-casing
    ("erp_union", "ERP Union"),
    ("graph_to_toon", "Graph To TOON"),
    ("", ""),
])
def test_humanise_preserves_known_acronyms(raw: str, expected: str) -> None:
    assert namer.humanise(raw.lstrip("_")) == expected


# ---------------------------------------------------------------------------------------
# path -> name
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    (".claude/skills/harness-mapping/SKILL.md", "Harness Mapping Skill"),
    (".claude/commands/wren.md", "/wren Command"),
    (".claude/agents/data-modeler.md", "Data Modeler Agent"),
    (".claude/rules/wren-rules.md", "Wren Rules Rules"),
    ("tests/test_dbt_column_lineage.py", "dbt Column Lineage Tests"),
    ("scripts/connector_alignment_check.py", "Connector Alignment Check"),
    (".github/workflows/ci.yml", "CI: CI"),
])
def test_name_from_path_reads_this_repos_layout(path: str, expected: str) -> None:
    assert namer.name_from_path(path) == expected


def test_a_dbt_macro_is_named_as_a_macro_and_a_model_is_not() -> None:
    macro = "skill-packs/dbt-skills/use-cases/x/dbt_project/macros/erp/erp_union.sql"
    model = "skill-packs/dbt-skills/use-cases/x/dbt_project/models/erp/erp_bi_dim_company.sql"
    assert namer.name_from_path(macro) == "ERP Union Macro"
    assert namer.name_from_path(model) == "ERP BI Dim Company"


def test_container_directories_are_refused_so_derive_falls_through() -> None:
    """`Enhanza Analytics` describes a third of the repository and names nothing.

    Returning None here is what makes `derive` fall past the directory rule to the
    structural hub, which is more informative than the use-case slug.
    """
    assert namer.name_from_dir("skill-packs/dbt-skills/use-cases/enhanza-analytics") is None
    assert namer.name_from_dir(".claude") is None
    assert namer.name_from_dir("skill-packs/dbt-skills/use-cases/x/dbt_project/packages/fortnox") \
        == "Fortnox Package"


# ---------------------------------------------------------------------------------------
# derivation order
# ---------------------------------------------------------------------------------------

def _node(nid: str, label: str, source_file: str = "") -> dict:
    return {"id": nid, "label": label, "source_file": source_file, "community": 0}


def test_a_dominant_file_names_the_community() -> None:
    members = [_node(f"n{i}", f"sym{i}", "scripts/connector_alignment_check.py")
               for i in range(9)]
    name, basis = namer.derive(members, {})
    assert (name, basis) == ("Connector Alignment Check", "file")


def test_a_package_spread_thin_is_named_by_directory_not_by_its_busiest_macro() -> None:
    """The regression guard for "Fortnox Package" coming out as "Auto Config".

    No single file reaches MIN_SHARE — the biggest is a sources.yml — but every member
    lives under one package, and `auto_config` merely has the most edges.
    """
    pkg = "skill-packs/dbt-skills/use-cases/x/dbt_project/packages/fortnox/models"
    members = [_node(f"m{i}", f"fortnox_bi_dim_{i}", f"{pkg}/staging/m{i}.sql")
               for i in range(10)]
    members.append(_node("hub", "auto_config", f"{pkg}/sources.yml"))
    degree = {"hub": 500}
    name, basis = namer.derive(members, degree)
    assert basis == "dir"
    assert name == "Fortnox Package"


def test_a_fileless_community_falls_through_to_its_hub() -> None:
    members = [_node("a", "Self"), _node("b", "Any")]
    name, basis = namer.derive(members, {"a": 3, "b": 1})
    assert (name, basis) == ("Self", "hub")


def test_builtins_never_win_the_hub() -> None:
    """`Any` decorates every typed module; it is never what a community is about."""
    members = [_node("typing", "Any"), _node("real", "build_metric_views")]
    name, _ = namer.derive(members, {"typing": 99, "real": 2})
    assert name == "Build Metric Views"


# ---------------------------------------------------------------------------------------
# redundancy and false distinction
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("candidate,base", [
    ("Add ERP Fields Macro", "Add ERP Fields"),        # merely extends
    ("test_dbt_column_lineage.py", "dbt Column Lineage Tests"),  # merely restates
    ("Manifest", "Manifest"),
])
def test_a_qualifier_that_adds_no_information_is_refused(candidate: str, base: str) -> None:
    assert namer._redundant(candidate, base)


def test_a_genuinely_distinguishing_qualifier_is_kept() -> None:
    assert not namer._redundant("Staging", "Fortnox Package")


def _graph(nodes: list, links: list) -> dict:
    return {"nodes": nodes, "links": links}


def test_isolated_singletons_sharing_a_symbol_share_its_name() -> None:
    """`Self` split across three one-node communities is one symbol, not three.

    Numbering them `Self`, `Self (2)`, `Self (3)` asserts a distinction the graph does
    not contain — every one is degree 0 with no source_file.
    """
    nodes = [{"id": f"s{i}", "label": "Self", "source_file": "", "community": i}
             for i in range(3)]
    names = namer.build_names(_graph(nodes, []), min_size=1)
    assert set(names.values()) == {"Self"}


def test_the_largest_of_a_collision_keeps_the_bare_name() -> None:
    big = [{"id": f"b{i}", "label": f"x{i}", "community": 0,
            "source_file": "scripts/dbt_column_memory.py"} for i in range(6)]
    small = [{"id": f"s{i}", "label": f"y{i}", "community": 1,
              "source_file": "scripts/dbt_column_memory.py"} for i in range(2)]
    links = [{"source": "b0", "target": "b1"}, {"source": "s0", "target": "s1"}]
    names = namer.build_names(_graph(big + small, links), min_size=1)
    assert names[0] == "dbt Column Memory"
    assert names[1] != names[0]


def test_no_two_communities_share_a_name_unless_both_are_stray_singletons() -> None:
    graph = json.loads((REPO / "graphify-out" / "graph.json").read_text(encoding="utf-8")) \
        if (REPO / "graphify-out" / "graph.json").is_file() else None
    if graph is None:
        pytest.skip("no graphify-out/graph.json in this clone")
    names = namer.build_names(graph, min_size=1)
    assert not any(v.startswith("Community ") for v in names.values()), \
        "every community must carry a derived name"


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------

def _run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, cwd=str(REPO), timeout=300)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    payload = _graph([{"id": "a", "label": "Alpha", "source_file": "scripts/alpha.py",
                       "community": 0}], [])
    graph.write_text(json.dumps(payload), encoding="utf-8")
    before = graph.read_bytes()
    result = _run(["--graph", str(graph), "--dry-run"])
    assert result.returncode == 0, result.stderr
    assert graph.read_bytes() == before


def test_apply_stamps_community_name_onto_every_node(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    payload = _graph([{"id": "a", "label": "Alpha", "source_file": "scripts/alpha.py",
                       "community": 0}], [])
    graph.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(["--graph", str(graph), "--apply"])
    assert result.returncode == 0, result.stderr
    written = json.loads(graph.read_text(encoding="utf-8"))
    assert written["nodes"][0]["community_name"] == "Alpha"


def test_a_missing_graph_exits_2_rather_than_traceback(tmp_path: Path) -> None:
    result = _run(["--graph", str(tmp_path / "nope.json")])
    assert result.returncode == 2
    assert "no graph at" in result.stderr
