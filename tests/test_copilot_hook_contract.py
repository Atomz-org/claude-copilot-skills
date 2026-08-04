"""End-to-end contract for the Copilot PreToolUse hook.

The failure this pins: the hook used to print nothing for every command it did
not rewrite. On a runtime that fails **open** (Claude Code) silence means "no
opinion". On a runtime that requires a decision from every registered hook and
denies without one, that same silence blocks every tool call the agent makes —
while the hook exits 0 and logs nothing, so the cause is invisible.

`test_fail_closed_runtime_lets_every_call_through` is the end-to-end check: it
drives the real hook through a runtime simulator that denies on silence, and
asserts nothing is ever blocked.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COPILOT_HOOK = REPO_ROOT / ".copilot" / "hooks" / "toon_graphify_pipe.py"
CLAUDE_HOOK = REPO_ROOT / "scripts" / "hooks" / "toon_graphify_pipe.py"

# Every shape a PreToolUse hook can be handed, including the malformed ones.
PAYLOADS = {
    "ordinary command": b'{"tool_name":"Bash","tool_input":{"command":"git status"}}',
    "dangerous command": b'{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}',
    "bare graphify": b'{"tool_name":"Bash","tool_input":{"command":"graphify query \\"x\\""}}',
    "composed graphify": b'{"tool_name":"Bash","tool_input":{"command":"graphify query \\"x\\" | head"}}',
    "already routed": b'{"tool_name":"Bash","tool_input":{"command":"graphify query \\"x\\" | graph_to_toon"}}',
    "non-Bash tool": b'{"tool_name":"Read","tool_input":{"file_path":"a.py"}}',
    "missing tool_input": b'{"tool_name":"Bash"}',
    "null tool_input": b'{"tool_name":"Bash","tool_input":null}',
    "command not a string": b'{"tool_name":"Bash","tool_input":{"command":42}}',
    "json but not an object": b'["not", "an", "object"]',
    "malformed json": b"not json at all",
    "empty stdin": b"",
    "invalid utf-8": b"\xff\xfe\x00garbage",
}


def run_hook(hook: Path, payload: bytes) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(hook)],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


# --------------------------------------------------------------------------
# the contract itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_hook_always_exits_zero_and_answers(name: str) -> None:
    result = run_hook(COPILOT_HOOK, PAYLOADS[name])

    assert result.returncode == 0, f"{name}: exit {result.returncode}"
    assert result.stderr == b"", f"{name}: wrote to stderr: {result.stderr!r}"
    assert result.stdout.strip(), f"{name}: silent — a fail-closed runtime reads this as a denial"
    json.loads(result.stdout.decode("utf-8"))  # raises if unparseable


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_hook_never_denies(name: str) -> None:
    body = json.loads(run_hook(COPILOT_HOOK, PAYLOADS[name]).stdout.decode("utf-8"))

    decisions = [body.get("permissionDecision"), body.get("hookSpecificOutput", {}).get("permissionDecision")]
    assert "deny" not in decisions
    assert body.get("continue") is True


@pytest.mark.parametrize(
    "name",
    [n for n in sorted(PAYLOADS) if n != "bare graphify"],
)
def test_non_rewrite_grants_no_permission(name: str) -> None:
    """A hook with no security role must not be able to wave a command through.

    Answering is required; answering "allow" to everything would make this hook
    a permission bypass sitting in front of every guardrail.
    """
    body = json.loads(run_hook(COPILOT_HOOK, PAYLOADS[name]).stdout.decode("utf-8"))

    assert "permissionDecision" not in body
    assert "permissionDecision" not in body.get("hookSpecificOutput", {})
    assert "updatedInput" not in body


def test_dangerous_command_is_not_allowed_by_this_hook() -> None:
    """The guardrail's job stays the guardrail's. This hook stays out of it."""
    body = json.loads(run_hook(COPILOT_HOOK, PAYLOADS["dangerous command"]).stdout.decode("utf-8"))

    assert body.get("permissionDecision") is None
    assert body.get("hookSpecificOutput", {}).get("permissionDecision") is None


# --------------------------------------------------------------------------
# the rewrite still works
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not (REPO_ROOT / "rust" / "toon" / "bin" / "graph_to_toon").is_file(),
    reason="serializer not built (./scripts/build_toon_rs.sh)",
)
def test_bare_graphify_is_rewritten_through_the_serializer() -> None:
    body = json.loads(run_hook(COPILOT_HOOK, PAYLOADS["bare graphify"]).stdout.decode("utf-8"))

    assert body["permissionDecision"] == "allow"
    command = body["updatedInput"]["command"]
    assert command.startswith('graphify query "x"')
    assert "graph_to_toon" in command and "--passthrough" in command
    # both spellings carry the same answer, so either reader agrees
    assert body["hookSpecificOutput"]["updatedInput"]["command"] == command


@pytest.mark.parametrize("name", ["composed graphify", "already routed"])
def test_composed_commands_are_left_alone(name: str) -> None:
    body = json.loads(run_hook(COPILOT_HOOK, PAYLOADS[name]).stdout.decode("utf-8"))

    assert "updatedInput" not in body


def test_answers_even_when_the_serializer_is_not_built(tmp_path: Path) -> None:
    """A fresh clone has no Rust binary. It must still answer, not fall silent."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    stand_in = hooks / "toon_graphify_pipe.py"
    shutil.copy(COPILOT_HOOK, stand_in)  # REPO resolves to tmp_path: no rust/ tree

    result = run_hook(stand_in, PAYLOADS["bare graphify"])

    assert result.returncode == 0
    body = json.loads(result.stdout.decode("utf-8"))
    assert body.get("continue") is True
    assert "updatedInput" not in body  # degraded to raw graphify output


# --------------------------------------------------------------------------
# end to end, against a runtime that fails closed
# --------------------------------------------------------------------------


def simulate_strict_runtime(payload: bytes) -> tuple[bool, str]:
    """A PreToolUse runtime that denies unless the hook returns a usable answer.

    This is the behaviour the old hook could not survive: no output, no run.
    Returns (allowed, why).
    """
    result = run_hook(COPILOT_HOOK, payload)
    if result.returncode != 0:
        return False, f"hook exited {result.returncode}"
    if not result.stdout.strip():
        return False, "hook returned no decision"
    try:
        body = json.loads(result.stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return False, "hook returned unparseable output"
    if body.get("continue") is not True:
        return False, "hook did not signal continue"
    if body.get("permissionDecision") == "deny":
        return False, body.get("permissionDecisionReason", "denied")
    return True, "proceeded"


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_fail_closed_runtime_lets_every_call_through(name: str) -> None:
    allowed, why = simulate_strict_runtime(PAYLOADS[name])

    assert allowed, f"{name} was blocked by the hook: {why}"


def test_strict_runtime_would_have_caught_the_old_silent_hook(tmp_path: Path) -> None:
    """The simulator is only meaningful if it fails on the shape that was broken.

    Without this, `test_fail_closed_runtime_lets_every_call_through` could pass
    against a simulator that never blocks anything.
    """
    silent = tmp_path / "silent_hook.py"
    silent.write_text("import sys\nsys.stdin.buffer.read()\nsys.exit(0)\n", encoding="utf-8")

    result = run_hook(silent, PAYLOADS["ordinary command"])

    assert result.returncode == 0
    assert result.stdout == b""  # exactly the old behaviour: exit 0, say nothing


# --------------------------------------------------------------------------
# the Claude Code twin is unchanged
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ordinary command", "non-Bash tool", "malformed json"])
def test_claude_hook_stays_silent(name: str) -> None:
    """Claude Code reads silence as "no opinion" — do not make it noisy."""
    result = run_hook(CLAUDE_HOOK, PAYLOADS[name])

    assert result.returncode == 0
    assert result.stdout == b""
