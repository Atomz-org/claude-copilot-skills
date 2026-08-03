"""Every hook command in .claude/settings.json must run outside Claude Code.

The failure this pins, observed from a GitHub Copilot CLI session in this repo:

    bash: /scripts/hooks/toon_prompt_context.sh: No such file or directory

$CLAUDE_PROJECT_DIR is set by Claude Code and by no other harness. Anything else
that reads this file expands it to the empty string, the path becomes absolute
at the filesystem root, bash exits 127, and a runtime that treats a failing
PreToolUse hook as a refusal blocks every tool call the agent makes. The agent
reports that it cannot run anything at all; the real cause is a single line of
'No such file or directory' on a stream nobody reads.

The same class of bug is an absolute path into one developer's home directory:
correct on that laptop, exit 127 in CI and in every repository that consumes
this module as a submodule.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

BASH_PAYLOAD = '{"tool_name":"Bash","tool_input":{"command":"git status"}}'
PUSH_PAYLOAD = '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'


def hook_commands() -> list[tuple[str, str, str]]:
    """(event, matcher, command) for every hook registered in settings.json."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    out = []
    for event, groups in settings["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                out.append((event, group.get("matcher", "*"), hook["command"]))
    return out


COMMANDS = hook_commands()
IDS = [f"{event}:{matcher}" for event, matcher, _ in COMMANDS]


def run_command(command: str, payload: str, *, env: dict | None = None, cwd: Path | None = None):
    """Run a hook command the way a runtime does: sh -c, payload on stdin."""
    import os

    run_env = os.environ.copy()
    run_env.pop("CLAUDE_PROJECT_DIR", None)  # the condition that broke it
    if env:
        run_env.update(env)
    return subprocess.run(
        ["sh", "-c", command],
        input=payload.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=run_env,
        cwd=str(cwd or REPO_ROOT),
        check=False,
    )


# --------------------------------------------------------------------------
# static shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize("event,matcher,command", COMMANDS, ids=IDS)
def test_no_hardcoded_home_path(event: str, matcher: str, command: str) -> None:
    """A path under /Users or /home is unsatisfiable for every other consumer."""
    assert "/Users/" not in command, f"{event}:{matcher} hardcodes a macOS home path"
    assert "/home/" not in command, f"{event}:{matcher} hardcodes a Linux home path"


@pytest.mark.parametrize("event,matcher,command", COMMANDS, ids=IDS)
def test_project_dir_is_never_used_without_a_fallback(event: str, matcher: str, command: str) -> None:
    """`$CLAUDE_PROJECT_DIR` alone is empty everywhere except Claude Code."""
    if "CLAUDE_PROJECT_DIR" not in command:
        return
    assert "${CLAUDE_PROJECT_DIR:-" in command, (
        f"{event}:{matcher} uses $CLAUDE_PROJECT_DIR with no fallback; "
        "outside Claude Code it expands to '' and the path resolves to /"
    )


# --------------------------------------------------------------------------
# behaviour without Claude Code's environment
# --------------------------------------------------------------------------


@pytest.mark.parametrize("event,matcher,command", COMMANDS, ids=IDS)
def test_every_hook_succeeds_without_claude_project_dir(event: str, matcher: str, command: str) -> None:
    result = run_command(command, BASH_PAYLOAD)

    assert result.returncode == 0, (
        f"{event}:{matcher} exited {result.returncode} with CLAUDE_PROJECT_DIR unset "
        f"-- a fail-closed runtime blocks every tool call on this. "
        f"stderr={result.stderr.decode('utf-8', 'replace').strip()!r}"
    )
    assert b"No such file or directory" not in result.stderr


@pytest.mark.parametrize("event,matcher,command", COMMANDS, ids=IDS)
def test_every_hook_succeeds_from_a_subdirectory(event: str, matcher: str, command: str) -> None:
    """Hooks may run with the cwd somewhere below the root; $PWD alone is not enough."""
    result = run_command(command, BASH_PAYLOAD, cwd=REPO_ROOT / "scripts")

    assert result.returncode == 0, (
        f"{event}:{matcher} exited {result.returncode} when run from scripts/"
    )


def test_prompt_context_hook_still_injects_its_line() -> None:
    """Succeeding by doing nothing would pass the tests above and help nobody."""
    command = next(c for e, _, c in COMMANDS if e == "UserPromptSubmit")
    result = run_command(command, "")

    assert result.returncode == 0
    assert b"toon-pipeline" in result.stdout


def test_graphify_rewrite_still_fires_without_claude_project_dir() -> None:
    serializer = REPO_ROOT / "rust" / "toon" / "bin" / "graph_to_toon"
    if not serializer.is_file():
        pytest.skip("serializer not built (./scripts/build_toon_rs.sh)")

    command = next(c for e, m, c in COMMANDS if m == "Bash" and "toon_graphify_pipe" in c)
    payload = '{"tool_name":"Bash","tool_input":{"command":"graphify query \\"x\\""}}'
    result = run_command(command, payload)

    assert result.returncode == 0
    body = json.loads(result.stdout.decode("utf-8"))
    assert "graph_to_toon" in body["hookSpecificOutput"]["updatedInput"]["command"]


# --------------------------------------------------------------------------
# the guardrail keeps guarding
# --------------------------------------------------------------------------


def guardrail_command() -> str:
    return next(c for e, m, c in COMMANDS if e == "PreToolUse" and "block-dangerous-git" in c)


@pytest.mark.parametrize("cwd", [None, "scripts"], ids=["root", "subdirectory"])
def test_guardrail_still_blocks_without_claude_project_dir(cwd) -> None:
    """Portability must not be bought by making the guardrail unreachable."""
    result = run_command(
        guardrail_command(), PUSH_PAYLOAD, cwd=REPO_ROOT / cwd if cwd else None
    )

    assert result.returncode == 2
    assert b"BLOCKED" in result.stderr


def test_guardrail_allows_a_safe_command() -> None:
    assert run_command(guardrail_command(), BASH_PAYLOAD).returncode == 0


def test_guardrail_fails_closed_when_its_script_is_missing(tmp_path: Path) -> None:
    """Documented asymmetry: the optional hooks degrade, this one must not.

    A guardrail that silently no-ops when its script disappears is worse than
    one that blocks, so it is deliberately left without a `|| true`.
    """
    result = run_command(
        guardrail_command(), PUSH_PAYLOAD, env={"CLAUDE_PROJECT_DIR": str(tmp_path)}
    )

    assert result.returncode != 0


# --------------------------------------------------------------------------
# optional hooks degrade instead of blocking
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,matcher,command",
    [c for c in COMMANDS if "block-dangerous-git" not in c[2]],
    ids=[f"{e}:{m}" for e, m, c in COMMANDS if "block-dangerous-git" not in c],
)
def test_optional_hooks_noop_when_their_script_is_absent(
    event: str, matcher: str, command: str, tmp_path: Path
) -> None:
    """A fresh clone, a missing binary, a partial checkout: never a hard stop."""
    result = run_command(command, BASH_PAYLOAD, env={"CLAUDE_PROJECT_DIR": str(tmp_path)})

    assert result.returncode == 0, (
        f"{event}:{matcher} exited {result.returncode} when its script was absent"
    )


# --------------------------------------------------------------------------
# the test is only meaningful if it fails on the shape that broke
# --------------------------------------------------------------------------


def test_the_original_broken_form_still_fails() -> None:
    """Guards against a fallback that silently stops being exercised."""
    broken = 'bash "$CLAUDE_PROJECT_DIR/scripts/hooks/toon_prompt_context.sh"'
    result = run_command(broken, "")

    assert result.returncode == 127
    assert b"No such file or directory" in result.stderr
