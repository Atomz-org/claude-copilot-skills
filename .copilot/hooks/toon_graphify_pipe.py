#!/usr/bin/env python3
"""PreToolUse hook: route graphify output through the TOON serializer, mechanically.

Registered in .claude/settings.json on the Bash matcher. When the model runs a
bare `graphify query|path|explain ...` command, this hook rewrites it to append

    | <repo>/rust/toon/bin/graph_to_toon --passthrough

so NODE/EDGE output enters the context as TOON without relying on the model
remembering to pipe. The serializer is the Rust binary built by
scripts/build_toon_rs.sh (~13ms per call); when it has not been built the hook
stays silent and graphify output arrives unserialized — build once per clone.
`--passthrough` guarantees the rewrite is harmless: input the serializer does
not recognize (e.g. `graphify path` prose) is forwarded unchanged.

The rewrite is deliberately conservative — it only fires on single-command
invocations. Anything containing a pipe, redirect, separator, or newline is
left untouched (a `|` may sit inside the query string itself, and rewriting
around user-composed plumbing risks changing semantics for no benefit).

Non-matching input produces no output at all, which Claude Code treats as
"no opinion". If the runtime does not support `updatedInput`, the emitted JSON
is ignored and the command runs unmodified — degradation is silent and safe.
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


def serializer_command() -> str | None:
    """The serializer to pipe through, or None when the binary is not built."""
    if RUST_BIN.is_file() and os.access(RUST_BIN, os.X_OK):
        return f'"{RUST_BIN}"'
    return None


def rewrite(command: str) -> str | None:
    """Return the piped command, or None when the hook should stay silent."""
    if not _GRAPHIFY_RE.match(command):
        return None
    if "graph_to_toon" in command:
        return None  # already routed
    if any(ch in command for ch in _UNSAFE_CHARS):
        return None  # composed command line: do not re-plumb it
    serializer = serializer_command()
    if serializer is None:
        return None  # binary not built: degrade to raw graphify output
    return f'{command.rstrip()} | {serializer} --passthrough'


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    updated = rewrite(command)
    if updated is None:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "toon-pipeline: graphify output serialized to TOON",
                    "updatedInput": {"command": updated},
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
