#!/usr/bin/env python3
"""PreToolUse hook: route graphify output through the TOON serializer.

Default behavior (Claude/CI):
- Rewrite bare `graphify query|path|explain ...` commands to append
  `| rust/toon/bin/graph_to_toon --passthrough` when the serializer binary
  exists, otherwise stay silent.

Compatibility mode (Copilot forwarder tests):
- If `COPILOT_TOON_HOOK` is set, forward the raw hook payload to that script.
  If the target is missing or fails, degrade to a no-op.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUST_BIN = REPO / "rust" / "toon" / "bin" / "graph_to_toon"

_GRAPHIFY_RE = re.compile(r"^\s*graphify\s+(query|path|explain)\b")
_UNSAFE_CHARS = set("|;&<>\n")

# Repo scripts whose findings are a uniform record list, and whose `--format json` output is
# measurably cheaper as TOON than as prose. Membership is decided by measurement on real
# enhanza-analytics data, never by how tabular the output looks:
#
#   connector_alignment_check.py   1332 -> 909 bytes   -31%   (28-finding case: -64.8%)
#   dbt_column_lineage.py          5445 -> 3212 bytes  -41%   (--column OrgName: -27%)
#
# Both emit one uniform record list — findings, and 5-field lineage edges — so the field
# names and the shared path prefix are stated once instead of once per row. `--limit`
# applies to text *and* json alike (default 40), so those two byte counts describe the
# same 40 records; TOON is not winning by truncating.
#
# Deliberately NOT here, each rejected on its own numbers:
#
#   dbt_manifest_to_graphify.py --dry-run    271 -> 633    +136%
#   dbt_column_memory.py (report)            297 -> 694    +133%
#   ontology_generator.py --check            195 -> 225     +15%
#   use_case_sync.py --check                 587 -> 854     +45%
#   wren_context_sync.py --check             145 -> 211     +45%
#   dbt_seed_generator.py --dry-run          228 -> 207      -9%   (21 bytes; noise)
#
# The first five lose for one reason: their text output is already a handful of lines of
# counts, and the JSON form carries more fields than the prose states. A format cannot
# rescue output that is not a record list. The sixth wins by an amount smaller than a
# single log line, which is not worth a rewritten command.
_TOON_SCRIPTS = (
    "scripts/connector_alignment_check.py",
    "scripts/dbt_column_lineage.py",
)


def serializer_command() -> str | None:
    if RUST_BIN.is_file() and os.access(RUST_BIN, os.X_OK):
        return f'"{RUST_BIN}"'
    return None


def rewrite(command: str) -> str | None:
    if "graph_to_toon" in command:
        return None
    if any(ch in command for ch in _UNSAFE_CHARS):
        return None
    serializer = serializer_command()
    if serializer is None:
        return None

    if _GRAPHIFY_RE.match(command):
        return f"{command.rstrip()} | {serializer} --passthrough"

    if any(script in command for script in _TOON_SCRIPTS):
        if "--format" in command:
            return None
        # `set -o pipefail` is not optional here. These scripts carry a `--check` gate that
        # signals failure through the exit status, and without pipefail the pipeline reports
        # the serializer's exit code instead — turning a red CI gate silently green.
        return (
            f"set -o pipefail; {command.rstrip()} --format json "
            f"| {serializer} --passthrough"
        )

    return None


def resolve_target() -> Path:
    override = os.environ.get("COPILOT_TOON_HOOK", "").strip()
    if override:
        return Path(override).expanduser()
    return REPO / ".copilot" / "hooks" / "toon_graphify_pipe.py"


def run_delegate(payload_bytes: bytes, target: Path) -> int:
    if not (target.is_file() and os.access(target, os.X_OK)):
        return 0
    try:
        proc = subprocess.run(
            [sys.executable, str(target)],
            input=payload_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception:
        return 0
    if proc.returncode != 0:
        return 0
    if proc.stdout:
        sys.stdout.buffer.write(proc.stdout)
    if proc.stderr:
        sys.stderr.buffer.write(proc.stderr)
    return 0


def main() -> int:
    payload_bytes = sys.stdin.buffer.read()

    # Compatibility mode: explicit delegate for Copilot override/forwarding.
    if os.environ.get("COPILOT_TOON_HOOK") is not None:
        return run_delegate(payload_bytes, resolve_target())

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
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