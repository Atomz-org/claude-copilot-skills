#!/usr/bin/env python3
"""PostToolUse hook: keep the column memory current when a dbt model changes.

The requirement this satisfies is "when a `.sql` model or anything else in a dbt project
changes, the column lineage is recreated". A hook is the only place that can be true without
depending on somebody remembering — `use_case_sync.py --check` catches drift at review time,
which is hours or days after the edit that caused it.

Two properties make a regeneration hook viable here at all:

  * **Detecting the change is free.** Every dbt manifest node carries a sha256 of the file it
    was parsed from, so which models moved is a few hundred file reads — about 0.3s on a
    359-model project, including loading the manifest.
  * **Rebuilding is nearly free too.** `dbt_column_memory.LineageCache` is keyed on each
    model's own content hash, so editing one model re-parses one model. Measured on
    enhanza-analytics: 1.6s cold, **0.35s with 358 cache hits and 1 miss**.

Without the second property this hook would have to be advisory — a 20-second sqlglot pass
after every file save is a hook that gets deleted within a day.

## What it deliberately does not do

**It never blocks.** PostToolUse runs after the edit has already landed, so a non-zero exit
cannot undo anything; it can only make the agent's next step fail for a reason unrelated to
what it was doing. Every failure path here exits 0.

**It never touches a use-case whose manifest is missing**, and it never runs `dbt`. A hook
that shells out to a warehouse-dependent command on file save is a hook that hangs.

**It only reacts to files inside a dbt project.** The matcher cannot express "a `.sql` under
`skill-packs/*/use-cases/*/dbt_project/`", so the path test is here. Anything else exits 0
silently and costs one process start.

Registered in `.claude/settings.json` on `PostToolUse` for `Edit|Write|MultiEdit|NotebookEdit`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Anything under a dbt project that can change what a column means. `.sql` is the model
# body; `.yml` carries the source definitions and the column docs the ontology reads;
# `dbt_project.yml` decides which models are enabled at all.
WATCHED_SUFFIXES = (".sql", ".yml", ".yaml")

TIMEOUT_SECONDS = 120


def repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(__file__).resolve().parents[2]


def edited_paths(payload: dict) -> list[str]:
    tool_input = payload.get("tool_input") or {}
    paths = [tool_input.get("file_path"), tool_input.get("notebook_path")]
    # MultiEdit-style payloads carry a list; take every path any of them names.
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            paths.append(edit.get("file_path"))
    return [p for p in paths if isinstance(p, str) and p]


def use_case_for(path: Path, root: Path) -> str | None:
    """The use-case slug whose dbt project contains `path`, or None.

    Matched structurally on `skill-packs/<pack>/use-cases/<slug>/dbt_project/...` rather
    than by scanning every use-case, so a repository with twenty of them costs the same as
    one with one.
    """
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except (ValueError, OSError):
        return None
    for index in range(len(parts) - 1):
        if parts[index] == "use-cases" and index + 2 < len(parts):
            if parts[index + 2] == "dbt_project":
                return parts[index + 1]
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    root = repo_root()
    script = root / "scripts" / "dbt_column_memory.py"
    if not script.is_file():
        return 0

    slugs: list[str] = []
    for raw in edited_paths(payload):
        path = Path(raw)
        if path.suffix.lower() not in WATCHED_SUFFIXES:
            continue
        slug = use_case_for(path, root)
        if slug and slug not in slugs:
            slugs.append(slug)
    if not slugs:
        return 0

    for slug in slugs:
        # `--stale-only` first: it needs no SQL parser and no ontology, so the common case —
        # an edit that changed nothing the lineage depends on — costs 0.3s and stops here.
        probe = subprocess.run(
            [sys.executable, str(script), "--use-case", slug, "--stale-only", "--format", "json"],
            capture_output=True, text=True, cwd=str(root), timeout=TIMEOUT_SECONDS, check=False,
        )
        if probe.returncode == 0:
            continue  # already current
        try:
            state = json.loads(probe.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError, ValueError):
            continue  # no manifest, or an unparseable answer: not this hook's problem

        rebuild = subprocess.run(
            [sys.executable, str(script), "--use-case", slug, "--write", "--format", "json"],
            capture_output=True, text=True, cwd=str(root), timeout=TIMEOUT_SECONDS, check=False,
        )
        if rebuild.returncode != 0:
            print(
                f"[column-memory] {slug}: {state.get('changed', 0)} dbt model(s) changed and "
                f"the rebuild failed — run: python3 scripts/dbt_column_memory.py "
                f"--use-case {slug} --write",
                file=sys.stderr,
            )
            continue
        try:
            result = json.loads(rebuild.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError, ValueError):
            continue
        print(
            f"[column-memory] {slug}: rebuilt {result.get('artifact', 'column-memory.json')} "
            f"after {state.get('changed', 0)} model change(s) — "
            f"{result.get('contracts', 0)} contracts, {result.get('bindings', 0)} bindings, "
            f"{result.get('drift', 0)} drift finding(s)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - a hook that raises is a hook that breaks the session
        raise SystemExit(0)
