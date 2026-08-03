#!/usr/bin/env python3
"""Copilot PreToolUse hook: route graphify output through the TOON serializer.

When the model runs a bare `graphify query|path|explain ...` command, this hook
rewrites it to append

    | <repo>/rust/toon/bin/graph_to_toon --passthrough

so NODE/EDGE output enters the context as TOON without relying on the model
remembering to pipe. The serializer is the Rust binary built by
scripts/build_toon_rs.sh (~13ms per call); when it has not been built the hook
falls back to plain graphify output — build once per clone. `--passthrough`
guarantees the rewrite is harmless: input the serializer does not recognize
(e.g. `graphify path` prose) is forwarded unchanged.

The rewrite is deliberately conservative — it only fires on single-command
invocations. Anything containing a pipe, redirect, separator, or newline is
left untouched (a `|` may sit inside the query string itself, and rewriting
around user-composed plumbing risks changing semantics for no benefit).

## Why this file always answers, and its Claude Code twin does not

Claude Code treats *no output* as "no opinion" and proceeds. This hook used to
rely on that, and stayed completely silent for every command it did not rewrite
— which is every command but one shape.

That is only safe on a runtime that fails **open**. A runtime that requires an
explicit decision from each registered PreToolUse hook, and denies when it does
not get one, reads that silence as a refusal and blocks *every tool call the
agent makes* — the hook that was meant to save tokens becomes the reason nothing
runs. The symptom is total and looks nothing like its cause, because the hook
exits 0 and prints no error.

So this file answers on every invocation, and its answer is never a denial:

  * a **rewrite** carries `permissionDecision: "allow"` plus `updatedInput`,
    because applying a rewrite requires a decision;
  * everything else carries **no `permissionDecision` at all** — just
    `continue: true`. That is deliberate. A blanket "allow" would be a
    permission-system bypass, and this hook has no security role: it must never
    be able to wave through a command that another guardrail would stop.

Both spellings — top-level and nested under `hookSpecificOutput` — are emitted,
so a runtime reading either shape finds the same answer.

Nothing here can raise. Any unexpected failure still prints the neutral answer
and exits 0, because a token optimisation must never be able to stop an agent.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUST_BIN = REPO / "rust" / "toon" / "bin" / "graph_to_toon"

_GRAPHIFY_RE = re.compile(r"^\s*graphify\s+(query|path|explain)\b")
_UNSAFE_CHARS = set("|;&<>\n")

_REASON = "toon-pipeline: graphify output serialized to TOON"


def serializer_command() -> str | None:
    """The serializer to pipe through, or None when the binary is not built."""
    if RUST_BIN.is_file() and os.access(RUST_BIN, os.X_OK):
        return f'"{RUST_BIN}"'
    return None


def rewrite(command: str) -> str | None:
    """Return the piped command, or None when the command should be left alone."""
    if not _GRAPHIFY_RE.match(command):
        return None
    if "graph_to_toon" in command:
        return None  # already routed
    if any(ch in command for ch in _UNSAFE_CHARS):
        return None  # composed command line: do not re-plumb it
    serializer = serializer_command()
    if serializer is None:
        return None  # binary not built: degrade to raw graphify output
    return f"{command.rstrip()} | {serializer} --passthrough"


def neutral_response() -> dict:
    """Proceed, with no opinion on permission.

    Explicitly free of `permissionDecision`: this hook must not be able to
    grant a permission that another guardrail would refuse.
    """
    return {
        "continue": True,
        "hookSpecificOutput": {"hookEventName": "PreToolUse"},
    }


def rewrite_response(updated: str) -> dict:
    """Allow the tool call, with the command replaced by its piped form."""
    return {
        "continue": True,
        "permissionDecision": "allow",
        "permissionDecisionReason": _REASON,
        "updatedInput": {"command": updated},
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": _REASON,
            "updatedInput": {"command": updated},
        },
    }


def decide(raw: bytes) -> dict:
    """Map raw stdin to a response. Never raises; unreadable input is neutral."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return neutral_response()
    if not isinstance(payload, dict):
        return neutral_response()
    if payload.get("tool_name") != "Bash":
        return neutral_response()
    tool_input = payload.get("tool_input")
    command = (tool_input or {}).get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return neutral_response()
    updated = rewrite(command)
    return neutral_response() if updated is None else rewrite_response(updated)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    try:
        response = decide(raw)
    except Exception:
        # A token optimisation must never be the reason an agent stops working.
        response = neutral_response()
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
