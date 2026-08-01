"""Tests for the PR impact-graph renderer and its workflow registration.

The renderer (scripts/pr_decision_diagram.py, with the graph work in
scripts/pr_impact_graph.py) maps a PR's changed line ranges onto nodes in
graphify's graph.json and draws the resulting subgraph. Four properties are
load-bearing and pinned here:

1. PR-specificity — two different diffs must produce two different diagrams.
   This is the whole point of the change; the previous renderer drew the same
   gate chain for every PR.
2. Hunk resolution — an edit inside a function body must select that function,
   not nothing and not the whole file.
3. Escaping — PR titles and branch names are attacker-controlled on fork PRs;
   nothing they contain may break out of a Mermaid label or a table cell.
4. Graceful degradation — a missing graph, an unextracted file type, or a
   truncated neighbour list must be stated in the output, never silently
   swallowed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pr_decision_diagram as pdd  # noqa: E402
import pr_impact_graph as pig  # noqa: E402

WORKFLOW = REPO / ".github" / "workflows" / "pr-decision-diagram.yml"
CI_REQUIREMENTS = REPO / ".github" / "requirements" / "ci.txt"

GATES = [
    "branch naming|pass|feat/no-ticket-sample",
    "test suite|pass|546 passed",
]

# A miniature graph in graphify's on-disk shape: two library files, one caller,
# one test. `contains` is the intra-file file->symbol edge graphify emits.
GRAPH = {
    "nodes": [
        {"id": "core", "label": "core.py", "source_file": "src/core.py", "source_location": "L1"},
        {"id": "core_a", "label": "alpha()", "source_file": "src/core.py", "source_location": "L10"},
        {"id": "core_b", "label": "beta()", "source_file": "src/core.py", "source_location": "L40"},
        {"id": "util", "label": "util.py", "source_file": "src/util.py", "source_location": "L1"},
        {"id": "util_h", "label": "helper()", "source_file": "src/util.py", "source_location": "L5"},
        {"id": "caller", "label": "caller.py", "source_file": "src/caller.py", "source_location": "L1"},
        {"id": "caller_run", "label": "run()", "source_file": "src/caller.py", "source_location": "L3"},
        {"id": "test", "label": "test_core.py", "source_file": "tests/test_core.py", "source_location": "L1"},
        {"id": "test_a", "label": "test_alpha()", "source_file": "tests/test_core.py", "source_location": "L4"},
        {"id": "lone", "label": "notes.md", "source_file": "docs/notes.md", "source_location": "L1"},
        # graphify emits a docstring node one line below the symbol it documents
        {
            "id": "core_a_doc",
            "label": "Alpha does the thing.",
            "source_file": "src/core.py",
            "source_location": "L11",
            "file_type": "rationale",
        },
    ],
    "links": [
        {"source": "core", "target": "core_a", "relation": "contains"},
        {"source": "core", "target": "core_b", "relation": "contains"},
        {"source": "util", "target": "util_h", "relation": "contains"},
        {"source": "caller", "target": "caller_run", "relation": "contains"},
        {"source": "test", "target": "test_a", "relation": "contains"},
        {"source": "caller_run", "target": "core_a", "relation": "calls"},
        {"source": "caller_run", "target": "core_a", "relation": "references"},
        {"source": "test_a", "target": "core_a", "relation": "calls"},
        {"source": "core_a", "target": "util_h", "relation": "imports"},
        {"source": "core_b", "target": "util_h", "relation": "calls"},
        {"source": "core_a", "target": "missing_node", "relation": "imports"},
    ],
}


def _graph_file(tmp_path) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(GRAPH), encoding="utf-8")
    return path


def _diff(path: str, start: int, count: int = 1) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -{start},{count} +{start},{count} @@\n"


def _render(tmp_path, lines=None, impact=None, **kw):
    src = tmp_path / "decisions.txt"
    src.write_text("\n".join(lines or GATES) + "\n", encoding="utf-8")
    records = pdd.parse_records(src)
    return pdd.render(
        records,
        kw.get("pr_number", "13"),
        kw.get("pr_title", "feat: sample"),
        kw.get("head_ref", "feat/no-ticket-sample"),
        impact,
    )


def _mermaid(document: str) -> str:
    return document.split("```mermaid")[1].split("```")[0]


# ---------------------------------------------------------------------------
# The diagram is a function of the diff
# ---------------------------------------------------------------------------

def test_different_diffs_produce_different_diagrams(tmp_path):
    """The defect this replaced: every PR rendered the identical flowchart."""
    graph = _graph_file(tmp_path)
    one = pdd.build_impact(graph, ["src/core.py"], _diff("src/core.py", 12))
    two = pdd.build_impact(graph, ["src/util.py"], _diff("src/util.py", 6))
    first = _mermaid(_render(tmp_path, impact=one))
    second = _mermaid(_render(tmp_path, impact=two))
    assert first != second
    # the boxed "changed" node is the PR's own content, and must differ
    assert 'C0["src/core.py' in first and 'C0["src/core.py' not in second
    assert 'C0["src/util.py' in second


def test_edit_inside_a_function_body_selects_that_function(tmp_path):
    """`alpha()` is declared at L10 and `beta()` at L40; L12 belongs to alpha."""
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 12))
    assert dict(impact["changed"])["src/core.py"] == ["alpha()"]


def test_dependents_and_dependencies_point_the_right_way(tmp_path):
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 12))
    dependents = dict(impact["dependents"])
    dependencies = dict(impact["dependencies"])
    # caller.py and test_core.py call into alpha(); alpha() imports util.py
    assert set(dependents) == {"src/caller.py", "tests/test_core.py"}
    assert dependents["src/caller.py"] == {"calls": 1, "references": 1}
    # beta() was not touched, so its own edge to util.py must not be counted
    assert dependencies == {"src/util.py": {"imports": 1}}

    mermaid = _mermaid(_render(tmp_path, impact=impact))
    assert re.search(r"D\d+ -->\|calls, references\| CHANGED", mermaid)
    assert re.search(r"CHANGED -->\|imports\| U\d+", mermaid)


def test_docstring_nodes_are_not_reported_as_touched_symbols(tmp_path):
    """A rationale node sits one line below its symbol and would double it."""
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 11))
    assert dict(impact["changed"])["src/core.py"] == ["alpha()"]


def test_two_changed_files_that_reference_each_other_are_linked(tmp_path):
    """A self-contained PR must still draw edges, not a box of loose nodes."""
    impact = pdd.build_impact(
        _graph_file(tmp_path),
        ["src/core.py", "src/caller.py"],
        _diff("src/core.py", 12) + _diff("src/caller.py", 3),
    )
    assert dict(impact["internal"]) == {("src/caller.py", "src/core.py"): {"calls": 1, "references": 1}}
    # caller.py is inside the PR, so it is not also drawn as an outside dependent
    assert "src/caller.py" not in dict(impact["dependents"])
    mermaid = _mermaid(_render(tmp_path, impact=impact))
    assert re.search(r"C\d+ -->\|calls, references\| C\d+", mermaid)


def test_intra_file_containment_is_not_an_impact_edge(tmp_path):
    """`contains` is the bulk of the graph and says nothing about blast radius."""
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 12))
    assert "contains" not in _mermaid(_render(tmp_path, impact=impact))


def test_whole_file_is_used_when_the_diff_is_unavailable(tmp_path):
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], "")
    # the file node itself is a seed but stands for the module, not a symbol
    assert sorted(dict(impact["changed"])["src/core.py"]) == ["alpha()", "beta()"]


def test_module_level_edit_pulls_in_the_whole_file(tmp_path):
    """An import-line change is exactly when dependents matter most.

    The file node owns L1 up to the first symbol, so a hunk there would
    otherwise seed only the file node and report no dependents at all.
    """
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 2))
    assert sorted(dict(impact["changed"])["src/core.py"]) == ["alpha()", "beta()"]
    assert set(dict(impact["dependents"])) == {"src/caller.py", "tests/test_core.py"}
    assert "module scope" not in _mermaid(_render(tmp_path, impact=impact))


def test_a_file_with_only_a_module_node_is_labelled_module_scope(tmp_path):
    impact = pdd.build_impact(_graph_file(tmp_path), ["docs/notes.md"], _diff("docs/notes.md", 1))
    assert dict(impact["changed"])["docs/notes.md"] == []
    assert "module scope" in _mermaid(_render(tmp_path, impact=impact))


def test_edges_to_nodes_outside_the_graph_are_dropped(tmp_path):
    """graph.json contains edges to unresolved ids; they must not crash or draw."""
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 12))
    assert "missing_node" not in _mermaid(_render(tmp_path, impact=impact))


def test_deletion_only_hunk_still_selects_a_symbol(tmp_path):
    """`@@ -40,3 +40,0 @@` has no new-side lines but still changed beta()."""
    diff = "--- a/src/core.py\n+++ b/src/core.py\n@@ -40,3 +40,0 @@\n"
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py"], diff)
    assert dict(impact["changed"])["src/core.py"] == ["beta()"]


def test_renamed_file_diff_is_attributed_to_the_new_path():
    diff = "--- a/src/old.py\n+++ b/src/core.py\n@@ -1,0 +12,2 @@\n"
    assert pig.parse_diff(diff) == {"src/core.py": [(12, 13)]}


def test_deleted_file_hunks_are_ignored():
    diff = "--- a/src/gone.py\n+++ /dev/null\n@@ -1,5 +0,0 @@\n"
    assert pig.parse_diff(diff) == {}


# ---------------------------------------------------------------------------
# Degradation is stated, never silent
# ---------------------------------------------------------------------------

def test_missing_graph_says_so_in_the_diagram(tmp_path):
    impact = pdd.build_impact(tmp_path / "absent.json", ["src/core.py"], "")
    out = _render(tmp_path, impact=impact)
    assert not impact["available"]
    assert "No impact subgraph" in _mermaid(out)
    assert "graph.json was not built" in out


def test_unextracted_file_types_are_named(tmp_path):
    impact = pdd.build_impact(
        _graph_file(tmp_path),
        ["src/core.py", ".github/workflows/ci.yml"],
        _diff("src/core.py", 12),
    )
    assert impact["unextracted"] == [".github/workflows/ci.yml"]
    out = _render(tmp_path, impact=impact)
    assert "Not extracted by graphify" in out and "ci.yml" in out


def test_files_absent_from_the_graph_are_named_separately(tmp_path):
    impact = pdd.build_impact(_graph_file(tmp_path), ["src/core.py", "src/brand_new.py"], "")
    assert impact["missing"] == ["src/brand_new.py"]
    assert "Changed but absent from the code graph" in _render(tmp_path, impact=impact)


def test_neighbour_cap_is_reported_not_silently_applied(tmp_path):
    impact = pdd.build_impact(
        _graph_file(tmp_path), ["src/core.py"], _diff("src/core.py", 12), max_neighbours=1
    )
    assert impact["dropped"] == 1
    assert "further neighbour file(s) omitted" in _render(tmp_path, impact=impact)


def test_isolated_change_renders_a_valid_diagram(tmp_path):
    """A file nothing depends on must still produce a graph, not an empty fence."""
    impact = pdd.build_impact(_graph_file(tmp_path), ["docs/notes.md"], _diff("docs/notes.md", 1))
    mermaid = _mermaid(_render(tmp_path, impact=impact))
    assert "No cross-file dependents or dependencies" in mermaid
    assert "docs/notes.md" in mermaid


def test_corrupt_graph_degrades_instead_of_raising(tmp_path):
    bad = tmp_path / "graph.json"
    bad.write_text("{not json", encoding="utf-8")
    assert pdd.build_impact(bad, ["src/core.py"], "")["available"] is False


# ---------------------------------------------------------------------------
# Gate table, verdict, escaping
# ---------------------------------------------------------------------------

def test_gate_table_carries_every_gate_and_a_passing_verdict(tmp_path):
    out = _render(tmp_path, [
        "branch naming|pass|feat/no-ticket-sample",
        "test suite|pass|546 passed",
        "toon serializer build|skip|not present on this branch",
    ])
    assert out.startswith(pdd.MARKER)
    assert "```mermaid" in out and "flowchart LR" in out
    for gate in ("branch naming", "test suite", "toon serializer build"):
        assert f"| {gate} |" in out
    assert "**Verdict: mergeable by repository standards**" in out


def test_failed_gate_blocks_the_verdict(tmp_path):
    out = _render(tmp_path, [
        "branch naming|pass|ok",
        "conventional commits|fail|update stuff",
        "test suite|pass|546 passed",
    ])
    assert "**Verdict: BLOCKED**" in out
    assert "❌ fail" in out


def test_untrusted_labels_cannot_break_out(tmp_path):
    hostile = 'x"]:::changed\nPWNED["<script>|`rm -rf`'
    out = _render(
        tmp_path,
        ['branch naming|fail|detail with "quotes" and [brackets] and |pipes|'],
        pr_title=hostile,
        head_ref='evil"branch<name>',
    )
    assert 'x"]:::changed' not in out
    assert "<script>" not in out
    assert "&quot;" in out and "&lt;" in out
    table_rows = [ln for ln in out.splitlines() if ln.startswith("| branch naming")]
    assert table_rows and table_rows[0].count("|") == 4  # 3 columns exactly


def test_hostile_paths_in_the_graph_are_escaped(tmp_path):
    """graph.json is built from the PR's tree, so a path is attacker-controlled."""
    graph = tmp_path / "graph.json"
    graph.write_text(
        json.dumps({
            "nodes": [{
                "id": "n",
                "label": 'x"]:::changed',
                "source_file": 'src/"evil<x>.py',
                "source_location": "L1",
            }],
            "links": [],
        }),
        encoding="utf-8",
    )
    out = _render(tmp_path, impact=pdd.build_impact(graph, ['src/"evil<x>.py'], ""))
    assert 'x"]:::changed' not in out
    assert "&quot;evil&lt;x&gt;.py" in out


def test_long_labels_are_clipped(tmp_path):
    out = _render(tmp_path, [f"test suite|pass|{'x' * 300}"], pr_title="y" * 300)
    assert "…" in out
    assert "y" * 200 not in out


def test_unknown_status_degrades_to_skip(tmp_path):
    assert "⏭️ skip" in _render(tmp_path, ["weird gate|exploded|boom"])


def test_empty_input_fails_loudly(tmp_path):
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    assert pdd.main(["--input", str(src), "--out", str(tmp_path / "o.md")]) == 1


def test_main_wires_graph_diff_and_changed_files(tmp_path):
    """End-to-end through argv, the way the workflow invokes it."""
    decisions = tmp_path / "decisions.txt"
    decisions.write_text("\n".join(GATES) + "\n", encoding="utf-8")
    changed = tmp_path / "changed.txt"
    changed.write_text("src/core.py\n", encoding="utf-8")
    diff = tmp_path / "pr.diff"
    diff.write_text(_diff("src/core.py", 12), encoding="utf-8")
    out = tmp_path / "diagram.md"
    assert pdd.main([
        "--input", str(decisions),
        "--graph", str(_graph_file(tmp_path)),
        "--changed", str(changed),
        "--diff", str(diff),
        "--pr-number", "13",
        "--pr-title", "feat: sample",
        "--head-ref", "feat/no-ticket-sample",
        "--out", str(out),
    ]) == 0
    text = out.read_text(encoding="utf-8")
    assert "alpha()" in text and "src/caller.py" in text


# ---------------------------------------------------------------------------
# Workflow registration
# ---------------------------------------------------------------------------

def test_workflow_exists_and_is_wired_safely():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request" in text
    assert "pull-requests: write" in text
    # untrusted inputs must flow through env, not direct interpolation in run:
    assert "HEAD_REF: ${{ github.head_ref }}" in text
    assert "PR_TITLE: ${{ github.event.pull_request.title }}" in text
    for step in text.split("- name:"):
        if "run: |" in step and "${{ github.head_ref }}" in step.split("run: |")[1]:
            raise AssertionError("github.head_ref interpolated directly into a run script")
    assert "pr_decision_diagram.py" in text
    assert "GITHUB_STEP_SUMMARY" in text


def test_workflow_builds_the_graph_and_feeds_the_diff_to_the_renderer():
    """Without these inputs the diagram silently falls back to 'no graph'."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "graphify update . --no-cluster" in text, "graph must be rebuilt from the PR tree"
    requirements = CI_REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"graphifyy==\d+\.\d+\.\d+", requirements), "graphify version must be pinned"
    assert "git diff -U0" in text and "--diff-filter=d" in text
    for flag in ("--graph graphify-out/graph.json", "--changed", "--diff"):
        assert flag in text, f"renderer invoked without {flag}"
    # the diff must be captured before the drift gate mutates the work tree
    assert text.index("Collect PR diff") < text.index("Run decision gates")


def test_graph_output_directory_is_gitignored():
    """graphify writes into the work tree; the drift gate reads git status."""
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any(line.strip().rstrip("/") == "graphify-out" for line in ignored)


def test_graph_build_cannot_fail_the_workflow():
    """A graph failure must degrade the diagram, not break the PR comment."""
    text = WORKFLOW.read_text(encoding="utf-8")
    build = text.index("- name: Build code graph")
    assert "continue-on-error: true" in text[build : build + 300]


# ---------------------------------------------------------------------------
# Runs alongside the other PR workflows, on every PR commit
# ---------------------------------------------------------------------------

WORKFLOWS = REPO / ".github" / "workflows"
PR_WORKFLOWS = [
    WORKFLOWS / "pr-decision-diagram.yml",
    WORKFLOWS / "ci-quality-gate.yml",
    WORKFLOWS / "claude-code-review.yml",
]


def _pull_request_types(path: Path) -> set[str]:
    """Extract the `pull_request: types: [...]` set from a workflow file."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"pull_request:\s*\n\s*types:\s*\[([^\]]*)\]", text)
    assert match, f"{path.name} has no pull_request types block"
    return {t.strip() for t in match.group(1).split(",") if t.strip()}


def test_pr_workflows_fire_on_identical_triggers():
    """The diagram must run alongside the other PR workflows, not on a subset.

    Pinning the three trigger sets together means adding an event type to the
    quality gate later fails this test until the diagram gets it too.
    """
    sets = {p.name: _pull_request_types(p) for p in PR_WORKFLOWS}
    reference = sets["ci-quality-gate.yml"]
    assert "synchronize" in reference, "synchronize is what makes it run per commit"
    for name, types in sets.items():
        assert types == reference, f"{name} triggers {sorted(types)} != {sorted(reference)}"
    for path in PR_WORKFLOWS:
        assert "workflow_dispatch:" in path.read_text(encoding="utf-8"), path.name


def test_diagram_is_serialized_per_pr():
    """A superseded run must not overwrite the sticky comment with a stale verdict."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in text
    assert "cancel-in-progress: true" in text
    assert "group: pr-decision-diagram-" in text


def test_test_gate_has_pytest_installed():
    """pytest is not preinstalled on the runner; without it the gate always fails."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pytest" in CI_REQUIREMENTS.read_text(encoding="utf-8")
    install = text.index("pip install -q -r")
    assert install < text.index("Run decision gates")


def test_ci_requirements_path_matches_the_workflow():
    """A dangling path fails setup-python's cache step and the install step.

    `cache-dependency-path` and `pip install -r` both resolve against the repo
    root, so the requirements file has to exist exactly where they point.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    referenced = set(re.findall(r"[\w./-]*\.github/requirements/[\w.-]+", text))
    assert referenced, "workflow no longer references a requirements file"
    for path in referenced:
        assert (REPO / path).is_file(), f"{path} is referenced by the workflow but missing"
    assert "cache: 'pip'" in text and "cache-dependency-path:" in text


def test_scratch_files_stay_out_of_the_work_tree():
    """The drift gate reads `git status --porcelain`; scratch files would dirty it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "git status --porcelain" in text
    assert '"$RUNNER_TEMP/decisions.txt"' in text
    assert ": > decisions.txt" not in text
    artifacts = ("decisions.txt", "diagram.md", "pr_title.txt", "pr.json", "changed.txt", "pr.diff")
    for artifact in artifacts:
        for line in text.splitlines():
            stripped = line.strip()
            if artifact in stripped and not stripped.startswith("#"):
                assert "RUNNER_TEMP" in stripped, f"{artifact} written into the work tree: {stripped}"


def test_quality_gate_asserts_the_diagram_workflow_is_present():
    quality = (WORKFLOWS / "ci-quality-gate.yml").read_text(encoding="utf-8")
    assert "test -f .github/workflows/pr-decision-diagram.yml" in quality
