"""Pins for scripts/hooks/dbt_column_memory_watch.py.

Separate from `test_dbt_column_memory.py` because the hook is a separate unit with a
separate failure mode. The store's tests ask whether a column resolves correctly; these ask
whether the hook can hurt anything, and the answer has to be no under every input.

PostToolUse fires *after* the edit has landed, so a non-zero exit cannot undo the edit. All
it can do is fail the agent's next step for a reason that has nothing to do with what the
agent was doing. Every path therefore exits 0, and the tests below are mostly a catalogue of
inputs the hook does not own.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import dbt_column_memory as ccm  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "dbt_column_memory_watch.py"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "dbt_column_memory.py"), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300, check=False,
    )


def run_hook(payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(cwd or REPO_ROOT), timeout=300, check=False,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_name": "Edit"},
        {"tool_name": "Edit", "tool_input": {}},
        {"tool_name": "Edit", "tool_input": {"file_path": "/nowhere/x.sql"}},
        {"tool_name": "Write", "tool_input": {"file_path": str(REPO_ROOT / "README.md")}},
        {"tool_name": "Edit", "tool_input": {"file_path": str(REPO_ROOT / "scripts/x.py")}},
    ],
    ids=["empty", "no-input", "no-path", "outside-repo", "not-dbt", "python-file"],
)
def test_the_hook_is_silent_and_zero_on_anything_it_does_not_own(payload):
    """PostToolUse runs after the edit landed. A non-zero exit cannot undo it — it can only
    break the agent's next step for an unrelated reason."""
    result = run_hook(payload)

    assert result.returncode == 0
    assert result.stdout == ""


def test_the_hook_never_raises_on_malformed_stdin():
    result = subprocess.run(
        [sys.executable, str(HOOK)], input="not json at all",
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60, check=False,
    )

    assert result.returncode == 0


def test_the_hook_recognises_a_dbt_model_and_leaves_others_alone():
    root = REPO_ROOT
    inside = root / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/models/x.sql"
    outside = root / "skill-packs/dbt-skills/use-cases/enhanza-analytics/ontology/x.yml"

    import importlib.util

    spec = importlib.util.spec_from_file_location("hook", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    assert hook.use_case_for(inside, root) == "enhanza-analytics"
    assert hook.use_case_for(outside, root) is None, (
        "only files inside a dbt_project can change what a column means"
    )


def test_the_hook_rebuilds_the_store_when_a_model_actually_changes(tmp_path: Path):
    """The end-to-end claim: edit a .sql, and the committed artifact is current again."""
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    manifest = use_case / "dbt_project/target/manifest.json"
    artifact = ccm.artifact_path(use_case)
    if not manifest.is_file() or not artifact.is_file() or ccm.lineage_mod.sqlglot is None:
        pytest.skip("needs the real project, its artifact, and sqlglot")

    target = next(
        p for p in (use_case / "dbt_project/packages").rglob("*_erp_bi_*.sql")
    )
    original = target.read_bytes()
    artifact_before = artifact.read_bytes()
    try:
        target.write_bytes(original + b"\n-- hook test probe\n")
        assert run_cli("--use-case", "enhanza-analytics", "--stale-only").returncode == 1

        result = run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})

        assert result.returncode == 0
        assert "[column-memory]" in result.stderr
        assert run_cli("--use-case", "enhanza-analytics", "--stale-only").returncode == 0
    finally:
        target.write_bytes(original)
        artifact.write_bytes(artifact_before)
