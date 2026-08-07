"""Every workflow's `on:` keys must be triggers GitHub actually accepts.

An unknown `on:` key does not merely fail to fire the job it was added for — GitHub stops
loading the file, so every *other* trigger in it dies too. A workflow whose schedule was
silently disabled looks exactly like one whose schedule has nothing to do.

This was not hypothetical. `coderabbit-issues.yml` was first written with
`pull_request_review_thread: [resolved]`, which is a **webhook** event and not a workflow
trigger, next to the `schedule:` that is the only reliable way to notice a resolved thread.
The invalid key would have taken the sweep down with it.

The allowed set is read from GitHub's own workflow schema when the network is there, and
falls back to a pinned copy when it is not — a check that goes red on an offline laptop
gets switched off, and one that silently passes offline is not a check.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
SCHEMA_URL = "https://json.schemastore.org/github-workflow.json"

# Read off the schema on 2026-08-07. The fallback exists so this test means something
# without a network; the live fetch is what keeps it honest as GitHub adds events.
PINNED = {
    "branch_protection_rule", "check_run", "check_suite", "create", "delete", "deployment",
    "deployment_status", "discussion", "discussion_comment", "fork", "gollum",
    "issue_comment", "issues", "label", "merge_group", "milestone", "page_build", "project",
    "project_card", "project_column", "public", "pull_request", "pull_request_review",
    "pull_request_review_comment", "pull_request_target", "push", "registry_package",
    "release", "repository_dispatch", "schedule", "status", "watch", "workflow_call",
    "workflow_dispatch", "workflow_run",
}


def allowed_triggers() -> set:
    try:
        with urllib.request.urlopen(SCHEMA_URL, timeout=15) as response:
            schema = json.loads(response.read())
        branch = next(b for b in schema["properties"]["on"]["oneOf"] if "properties" in b)
        live = set(branch["properties"])
        # A live set that lost entries is a schema change, not a repository defect — union
        # rather than replace, so this never fails on somebody else's edit.
        return live | PINNED
    except (urllib.error.URLError, OSError, KeyError, StopIteration, ValueError):
        return PINNED


def workflow_events(path: Path):
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # PyYAML resolves the bare key `on` to the boolean True (YAML 1.1), which is why every
    # tool that reads workflows has this line.
    on = document.get(True, document.get("on"))
    if isinstance(on, str):
        return [on]
    return list(on or [])


def test_every_workflow_trigger_is_one_github_accepts() -> None:
    allowed = allowed_triggers()
    offenders = {
        path.name: [e for e in workflow_events(path) if e not in allowed]
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        f"unknown `on:` key(s) {offenders} — GitHub will refuse to load the whole file, "
        "silently disabling every other trigger in it"
    )


def test_the_resolved_thread_event_is_still_not_a_trigger() -> None:
    """The specific claim the CodeRabbit bridge's design rests on.

    If GitHub ever promotes it, this fails and the bridge can gain a push path instead of
    waiting on its 15-minute sweep — which is the only reason the sweep exists.
    """
    if "pull_request_review_thread" in allowed_triggers():
        pytest.fail(
            "`pull_request_review_thread` is now a workflow trigger — add it to "
            ".github/workflows/coderabbit-issues.yml and drop the note in CLAUDE.md"
        )


def test_the_coderabbit_bridge_keeps_a_schedule() -> None:
    """It is the only mechanism that notices a resolved thread; without it the issues
    never close and nothing says so."""
    path = WORKFLOWS / "coderabbit-issues.yml"
    if not path.exists():
        pytest.skip("bridge workflow not on this branch")
    assert "schedule" in workflow_events(path)


def test_every_workflow_parses() -> None:
    yaml = pytest.importorskip("yaml")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict), path.name
        assert document.get("jobs"), f"{path.name}: no jobs"
