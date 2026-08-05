"""Tests for the per-prompt TOON pipeline enforcement.

The pipeline (Graphify → TOON → LLM context → JSON out) must not depend on the
model remembering to run it, so it is enforced by two hooks registered in
.claude/settings.json:

- UserPromptSubmit  scripts/hooks/toon_prompt_context.sh
    stdout is injected into context on every prompt — the per-prompt assertion.
- PreToolUse (Bash) scripts/hooks/toon_graphify_pipe.py
    rewrites bare `graphify query|path|explain` commands to pipe through the
    Rust serializer rust/toon/bin/graph_to_toon --passthrough, and stays
    silent when the binary has not been built.

These tests pin three properties: the hooks are registered, the rewrite fires
exactly when it is safe (and only when the binary exists), and --passthrough
guarantees a rewritten command can never fail on unrecognized output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "hooks"))

import toon_graphify_pipe  # noqa: E402

PIPE_HOOK = REPO / "scripts" / "hooks" / "toon_graphify_pipe.py"
PROMPT_HOOK = REPO / "scripts" / "hooks" / "toon_prompt_context.sh"
SETTINGS = REPO / ".claude" / "settings.json"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_hook_files_exist():
    assert PIPE_HOOK.exists()
    assert PROMPT_HOOK.exists()


def test_settings_register_both_hooks():
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    pre = json.dumps(settings["hooks"]["PreToolUse"])
    prompt = json.dumps(settings["hooks"]["UserPromptSubmit"])
    assert "toon_graphify_pipe.py" in pre
    assert "toon_prompt_context.sh" in prompt
    # the git guardrail must survive our edit (standards.md requirement)
    assert "block-dangerous-git.sh" in pre


# ---------------------------------------------------------------------------
# Rewrite decision logic
# ---------------------------------------------------------------------------

def _with_binary(monkeypatch, tmp_path) -> Path:
    fake = tmp_path / "graph_to_toon"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", fake)
    return fake


def test_bare_graphify_commands_are_rewritten(monkeypatch, tmp_path):
    fake = _with_binary(monkeypatch, tmp_path)
    for cmd in (
        'graphify query "what depends on fct_orders" --budget 800',
        'graphify path "A" "B"',
        'graphify explain "GraphManager"',
        '  graphify query "leading whitespace"',
    ):
        rewritten = toon_graphify_pipe.rewrite(cmd)
        assert rewritten is not None, cmd
        assert rewritten.startswith(cmd.rstrip())
        assert rewritten.endswith("--passthrough")
        assert str(fake) in rewritten


def test_hook_stays_silent_when_binary_not_built(monkeypatch, tmp_path):
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", tmp_path / "absent")
    assert toon_graphify_pipe.rewrite('graphify query "q"') is None


def test_composed_or_foreign_commands_are_left_alone(monkeypatch, tmp_path):
    _with_binary(monkeypatch, tmp_path)  # even with the binary available
    for cmd in (
        "git status",                                   # not graphify
        "graphify update .",                            # not a read command
        "graphify install",                             # not a read command
        'graphify query "x" | head -5',                 # existing pipe
        'graphify query "x" > out.txt',                 # redirect
        'graphify query "a" && echo done',              # separator
        'graphify query "x"\necho second line',         # multi-line
        'graphify query "x" | rust/toon/bin/graph_to_toon',  # already routed
    ):
        assert toon_graphify_pipe.rewrite(cmd) is None, cmd


# ---------------------------------------------------------------------------
# Hook protocol over stdin/stdout
# ---------------------------------------------------------------------------

def _run_pipe_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPE_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )


def test_hook_emits_updated_input_for_matching_bash_command(toon_binary):
    result = _run_pipe_hook(
        {"tool_name": "Bash", "tool_input": {"command": 'graphify query "q"'}}
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "allow"
    updated = specific["updatedInput"]["command"]
    assert updated.endswith("--passthrough")
    assert str(toon_binary) in updated


def test_hook_stays_silent_for_non_matching_input():
    for payload in (
        {"tool_name": "Bash", "tool_input": {"command": "git status"}},
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
        {"tool_name": "Bash", "tool_input": {}},
    ):
        result = _run_pipe_hook(payload)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


def test_hook_survives_garbage_stdin():
    result = subprocess.run(
        [sys.executable, str(PIPE_HOOK)],
        input="not json at all", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Per-prompt context injection
# ---------------------------------------------------------------------------

def test_prompt_hook_emits_single_line_pipeline_assertion():
    result = subprocess.run(
        ["bash", str(PROMPT_HOOK)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1  # one line: this cost repeats on every prompt
    assert "graph_to_toon" in lines[0]
    assert "TOON" in lines[0]
    assert "--decode" in lines[0]


# ---------------------------------------------------------------------------------------
# Repo scripts whose findings are a uniform record list
# ---------------------------------------------------------------------------------------


def test_alignment_check_is_rewritten_to_json_toon(monkeypatch, tmp_path):
    fake = tmp_path / "graph_to_toon"
    fake.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", fake)

    cmd = "python3 scripts/connector_alignment_check.py --connector shopify --check"
    rewritten = toon_graphify_pipe.rewrite(cmd)
    assert rewritten is not None
    assert "--format json" in rewritten
    assert rewritten.endswith("--passthrough")
    # Without pipefail the pipeline reports the serializer's status, so a failing
    # `--check` would exit 0 and a red gate would go silently green.
    assert rewritten.startswith("set -o pipefail;")


def test_alignment_check_with_explicit_format_is_left_alone(monkeypatch, tmp_path):
    fake = tmp_path / "graph_to_toon"
    fake.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", fake)

    cmd = "python3 scripts/connector_alignment_check.py --format json"
    assert toon_graphify_pipe.rewrite(cmd) is None


def test_column_lineage_is_rewritten_to_json_toon(monkeypatch, tmp_path):
    """Lineage edges are a uniform 5-field list: 5445 -> 3212 bytes, -41%.

    `--limit` (default 40) applies to text and json alike, so both byte counts
    describe the same 40 records — TOON is not winning by truncating.
    """
    fake = tmp_path / "graph_to_toon"
    fake.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", fake)

    cmd = "python3 scripts/dbt_column_lineage.py --manifest target/manifest.json"
    rewritten = toon_graphify_pipe.rewrite(cmd)
    assert rewritten is not None
    assert "--format json" in rewritten
    assert rewritten.endswith("--passthrough")
    assert rewritten.startswith("set -o pipefail;")


def test_manifest_emitter_is_not_rewritten(monkeypatch, tmp_path):
    """Its text output is already smaller than its JSON; TOON would cost tokens."""
    fake = tmp_path / "graph_to_toon"
    fake.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", fake)

    cmd = "python3 scripts/dbt_manifest_to_graphify.py --manifest x.json"
    assert toon_graphify_pipe.rewrite(cmd) is None


def test_measured_losers_stay_unrouted(monkeypatch, tmp_path):
    """Routing is decided by bytes, not by how tabular the output looks.

    Each of these was measured on real enhanza-analytics data and came out larger
    as TOON than as prose, because its text form is a handful of lines of counts
    rather than a record list. `dbt_column_memory.py --concept` is the instructive
    one: it *looks* like a record list and briefly measured as a 82% win, but that
    was `--format json` silently ignoring `--concept` and emitting the summary
    instead. With the projection fixed the honest number is +30%, so it stays out.
    """
    fake = tmp_path / "graph_to_toon"
    fake.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", fake)

    for cmd in (
        "python3 scripts/dbt_column_memory.py --use-case enhanza-analytics",
        "python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --concept dim_articles",
        "python3 scripts/ontology_generator.py --use-case enhanza-analytics --check",
        "python3 scripts/use_case_sync.py --use-case enhanza-analytics --check",
        "python3 scripts/wren_context_sync.py --use-case enhanza-analytics --check",
        "python3 scripts/dbt_seed_generator.py --use-case enhanza-analytics --dry-run",
    ):
        assert toon_graphify_pipe.rewrite(cmd) is None, f"unexpectedly routed: {cmd}"


def test_script_rewrite_stays_silent_without_the_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(toon_graphify_pipe, "RUST_BIN", tmp_path / "absent")
    cmd = "python3 scripts/connector_alignment_check.py --check"
    assert toon_graphify_pipe.rewrite(cmd) is None
