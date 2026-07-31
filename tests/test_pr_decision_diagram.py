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
