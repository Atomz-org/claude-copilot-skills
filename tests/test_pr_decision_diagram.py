"""Tests for the PR decision diagram renderer and its workflow registration.

The renderer (scripts/pr_decision_diagram.py) turns per-gate `gate|status|
detail` records into a Mermaid flowchart posted on the PR. Two properties are
load-bearing and pinned here:

1. Escaping — PR titles and branch names are attacker-controlled on fork
   PRs; nothing they contain may break out of a Mermaid label or a markdown
   table cell.
2. Verdict wiring — any failed gate must flip the verdict to BLOCKED and get
   an explicit "blocks merge" edge, because the diagram's whole value is
   showing which decision stopped the merge.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pr_decision_diagram as pdd  # noqa: E402

WORKFLOW = REPO / ".github" / "workflows" / "pr-decision-diagram.yml"


def _render(tmp_path, lines, **kw):
    src = tmp_path / "decisions.txt"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records = pdd.parse_records(src)
    return pdd.render(
        records,
        kw.get("pr_number", "13"),
        kw.get("pr_title", "feat: sample"),
        kw.get("head_ref", "feat/no-ticket-sample"),
    )


def test_all_gates_render_in_order_with_status_classes(tmp_path):
    out = _render(tmp_path, [
        "branch naming|pass|feat/no-ticket-sample",
        "test suite|pass|546 passed",
        "toon serializer build|skip|not present on this branch",
    ])
    assert out.startswith(pdd.MARKER)
    assert "```mermaid" in out and "flowchart TD" in out
    body = out.replace("\n", " ")
    assert body.index("branch naming") < body.index("test suite") < body.index(
        "toon serializer build"
    )
    assert ":::pass" in out and ":::skip" in out
    assert 'V["Verdict: mergeable by repository standards"]:::verdict' in out


def test_failed_gate_blocks_the_verdict(tmp_path):
    out = _render(tmp_path, [
        "branch naming|pass|ok",
        "conventional commits|fail|update stuff",
        "test suite|pass|546 passed",
    ])
    assert 'V["Verdict: BLOCKED"]:::blocked' in out
    assert "G1 -. blocks merge .-> V" in out
    assert "G0 -. blocks merge .->" not in out  # only the failed gate blocks


def test_untrusted_labels_cannot_break_out(tmp_path):
    hostile = 'x"]:::pass\nPWNED["<script>|`rm -rf`'
    out = _render(
        tmp_path,
        ['branch naming|fail|detail with "quotes" and [brackets] and |pipes|'],
        pr_title=hostile,
        head_ref='evil"branch<name>',
    )
    # raw breakout tokens must not survive escaping
    assert 'x"]:::pass' not in out
    assert "<script>" not in out
    assert "&quot;" in out and "&lt;" in out
    # detail pipes are neutralized so the markdown table stays intact
    table_rows = [ln for ln in out.splitlines() if ln.startswith("| branch naming")]
    assert table_rows and table_rows[0].count("|") == 4  # 3 columns exactly


def test_long_details_are_clipped(tmp_path):
    out = _render(tmp_path, [f"test suite|pass|{'x' * 300}"])
    mermaid = out.split("```mermaid")[1].split("```")[0]
    assert "…" in mermaid
    assert "x" * 100 not in mermaid


def test_unknown_status_degrades_to_skip(tmp_path):
    out = _render(tmp_path, ["weird gate|exploded|boom"])
    assert ":::skip" in out


def test_empty_input_fails_loudly(tmp_path):
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    assert pdd.main(["--input", str(src), "--out", str(tmp_path / "o.md")]) == 1


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
    install = text.index("pip install -q pytest")
    assert install < text.index("Run decision gates")


def test_scratch_files_stay_out_of_the_work_tree():
    """The drift gate reads `git status --porcelain`; scratch files would dirty it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "git status --porcelain" in text
    assert '"$RUNNER_TEMP/decisions.txt"' in text
    assert ": > decisions.txt" not in text
    for artifact in ("decisions.txt", "diagram.md", "pr_title.txt", "pr.json"):
        for line in text.splitlines():
            stripped = line.strip()
            if artifact in stripped and not stripped.startswith("#"):
                assert "RUNNER_TEMP" in stripped, f"{artifact} written into the work tree: {stripped}"


def test_quality_gate_asserts_the_diagram_workflow_is_present():
    quality = (WORKFLOWS / "ci-quality-gate.yml").read_text(encoding="utf-8")
    assert "test -f .github/workflows/pr-decision-diagram.yml" in quality
