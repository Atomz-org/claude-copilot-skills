"""Tests for the stacked-delivery branch linter.

The linter exists because GitHub's stack feature checks none of this: it cares only that
each PR's base is the head of the PR below it. Two things remain this repository's problem,
and both fail silently:

1. **The branch grammar.** The lane and layer ordinal drive routing, review, and ordering.
   The pre-existing gate only checked the `<type>/` prefix, so everything after it drifted.
2. **Generated artifacts belong to the top layer only.** Every layer that regenerates
   rewrites the same wholesale-generated files, so a multi-layer stack collides with itself
   — the `.gitattributes` conflict class, produced by one delivery instead of two.

A legacy `<type>/<description>` branch must WARN, never fail: the repository is full of
them and a gate that reddens on correct history gets switched off.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import stack_lint  # noqa: E402


# ---------------------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("branch,lane,ordinal,layer", [
    ("feat/ACME-42-acme-fortnox-01-connector", "acme", "01", "connector"),
    ("feat/PLAT-51-platform-wren-cubes-02-semantic", "platform", "02", "semantic"),
    ("fix/ENG-7-acme-orders-04-hardening", "acme", "04", "hardening"),
    ("feat/no-ticket-platform-topic-01-foundation", "platform", "01", "foundation"),
])
def test_grammar_parses_lane_and_layer(branch, lane, ordinal, layer) -> None:
    got = stack_lint.parse(branch)
    assert got is not None, f"{branch} should parse"
    assert (got["lane"], got["ordinal"], got["layer"]) == (lane, ordinal, layer)


@pytest.mark.parametrize("branch", [
    "feature/ACME-42-acme-fortnox-01-connector",   # not a Conventional type
    "feat/ACME-42-acme-fortnox-1-connector",       # ordinal not zero-padded
    "feat/ACME-42-acme-fortnox-01",                # no layer name
    "acme/thing",
])
def test_grammar_rejects_malformed(branch) -> None:
    assert stack_lint.parse(branch) is None


def test_legacy_branch_warns_but_does_not_fail() -> None:
    """The repository's whole history uses this form; failing it would disable the gate."""
    result = stack_lint.lint("feat/no-ticket-wrenai-integration", "main")
    assert result["ok"] is True
    assert [f["severity"] for f in result["findings"]] == ["warn"]
    assert result["stack"] is None


def test_a_name_that_is_neither_grammar_nor_legacy_is_an_error() -> None:
    result = stack_lint.lint("feature/nope", "main")
    assert result["ok"] is False
    assert result["findings"][0]["check"] == "branch-grammar"


def test_trunk_is_refused_with_the_way_out() -> None:
    result = stack_lint.lint("main", "main")
    assert result["ok"] is False
    assert "git switch -c" in result["findings"][0]["fix"]


def test_every_finding_names_a_fix() -> None:
    """A gate that reports a problem without the remedy gets ignored."""
    for branch in ("main", "feature/nope", "feat/no-ticket-legacy-thing"):
        for finding in stack_lint.lint(branch, "main")["findings"]:
            assert finding.get("fix"), f"{branch}: {finding['check']} has no fix"


# ---------------------------------------------------------------------------------------
# Generated-path matching — the input to the layer rule
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    ("skill-packs/dbt-skills/use-cases/acme/ontology/index.json", True),
    ("skill-packs/dbt-skills/use-cases/acme/ontology/connectors/erp.ttl", True),
    ("skill-packs/dbt-skills/use-cases/acme/ontology/column-memory.json", True),
    ("skill-packs/dbt-skills/use-cases/acme/wren/models/fct/metadata.yml", True),
    ("skill-packs/dbt-skills/use-cases/acme/dbt_project/seeds/sample/raw.csv", True),
    (".claude/skills/wren-genbi/SKILL.md", True),
    ("references/anything.md", True),
    ("graphify-out/graph.json", True),
    # Hand-written source must never be mistaken for generated output.
    ("skill-packs/dbt-skills/use-cases/acme/dbt_project/models/staging/stg_a.sql", False),
    ("skill-packs/dbt-skills/use-cases/acme/dbt_project/models/sources.yml", False),
    ("skill-packs/wren-skills/.claude/skills/wren-genbi/SKILL.md", False),
    ("scripts/wren_context_sync.py", False),
    ("docs/BRANCHING_STRATEGY.md", False),
])
def test_generated_path_classification(path, expected) -> None:
    assert stack_lint.is_generated(path) is expected


def test_pack_source_is_not_generated_but_its_mirror_is() -> None:
    """The distinction the whole activation model rests on: edit the pack, never the mirror.

    A pack asset and its activated mirror have near-identical paths, and calling the pack
    copy 'generated' would block the only place a skill may legitimately be edited.
    """
    assert not stack_lint.is_generated("skill-packs/dbt-skills/.claude/rules/x.md")
    assert stack_lint.is_generated(".claude/rules/x.md")


# ---------------------------------------------------------------------------------------
# The layer rule
# ---------------------------------------------------------------------------------------


def test_lower_layer_touching_generated_files_is_an_error(monkeypatch) -> None:
    parsed = "feat/ACME-9-acme-topic-01-connector"
    monkeypatch.setattr(stack_lint, "sibling_layers", lambda p: [1, 2, 3])
    monkeypatch.setattr(stack_lint, "changed_files", lambda base, branch: [
        "skill-packs/dbt-skills/use-cases/acme/dbt_project/models/staging/stg_a.sql",
        "skill-packs/dbt-skills/use-cases/acme/ontology/column-memory.json",
    ])
    result = stack_lint.lint(parsed, "main")
    assert result["ok"] is False
    finding = [f for f in result["findings"] if f["check"] == "artifact-layer"][0]
    assert "top layer" in finding["detail"]
    assert result["stack"]["is_top"] is False


def test_top_layer_may_commit_generated_files(monkeypatch) -> None:
    """The top layer is exactly where regeneration is supposed to land."""
    monkeypatch.setattr(stack_lint, "sibling_layers", lambda p: [1, 2, 3])
    monkeypatch.setattr(stack_lint, "changed_files", lambda base, branch: [
        "skill-packs/dbt-skills/use-cases/acme/ontology/column-memory.json",
    ])
    result = stack_lint.lint("feat/ACME-9-acme-topic-03-hardening", "main")
    assert result["ok"] is True
    assert result["stack"]["is_top"] is True


def test_a_single_layer_branch_is_not_a_stack_and_is_not_policed(monkeypatch) -> None:
    """With no siblings there is no stack, so there is no 'top layer' to insist on."""
    monkeypatch.setattr(stack_lint, "sibling_layers", lambda p: [1])
    monkeypatch.setattr(stack_lint, "changed_files", lambda base, branch: [
        "skill-packs/dbt-skills/use-cases/acme/ontology/column-memory.json",
    ])
    result = stack_lint.lint("feat/ACME-9-acme-topic-01-connector", "main")
    assert result["ok"] is True


def test_lower_layer_with_only_handwritten_files_passes(monkeypatch) -> None:
    monkeypatch.setattr(stack_lint, "sibling_layers", lambda p: [1, 2])
    monkeypatch.setattr(stack_lint, "changed_files", lambda base, branch: [
        "skill-packs/dbt-skills/use-cases/acme/dbt_project/models/staging/stg_a.sql",
    ])
    result = stack_lint.lint("feat/ACME-9-acme-topic-01-connector", "main")
    assert result["ok"] is True


def test_oversized_stack_warns_without_failing(monkeypatch) -> None:
    monkeypatch.setattr(stack_lint, "sibling_layers", lambda p: [1, 2, 3, 4, 5])
    monkeypatch.setattr(stack_lint, "changed_files", lambda base, branch: [])
    result = stack_lint.lint("feat/ACME-9-acme-topic-05-extra", "main")
    assert result["ok"] is True
    assert any(f["check"] == "stack-size" for f in result["findings"])


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def test_check_exits_nonzero_only_on_an_error() -> None:
    def run(branch: str, check: bool = True) -> int:
        cmd = [sys.executable, str(REPO / "scripts/stack_lint.py"), "--branch", branch,
               "--format", "json"]
        if check:
            cmd.append("--check")
        return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO).returncode

    assert run("feature/nope") == 1
    assert run("feat/no-ticket-legacy-thing") == 0, "a legacy name must not fail the gate"
    assert run("feature/nope", check=False) == 0, "advisory mode never fails"


def test_json_output_is_one_parseable_line() -> None:
    """Matches the repository's emitter convention so a hook or gate can consume it."""
    import json

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/stack_lint.py"),
         "--branch", "feat/ACME-42-acme-fortnox-01-connector", "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["branch"] == "feat/ACME-42-acme-fortnox-01-connector"
