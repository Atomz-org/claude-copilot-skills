"""Tests for the skill-map pack and its deterministic runner.

The pack wraps an upstream Node CLI (https://github.com/PackMaaan/skill-map)
that has two halves: a deterministic scanner and a probabilistic layer that
queues LLM jobs. This repository uses only the first, and the whole point of the
integration is that the property is *enforced* rather than promised.

These tests pin three things:

- the no-LLM boundary — the runner's verb allowlist excludes every probabilistic
  verb family, and neither the pack docs nor CI instruct one;
- the pack's shape, including that activation tolerates its missing `agents/`;
- the nested Harness subgraph in the PR decision diagram, which must render only
  when a PR touches harness files and must never emit malformed Mermaid.

Nothing here invokes the `sm` CLI: the suite must pass on a runner with no Node
and no network. The runner's own network path is exercised in CI, where the
gate records a skip when it cannot run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pr_decision_diagram as pdd  # noqa: E402
import skill_map_scan as sms  # noqa: E402

PACK = REPO / "skill-packs" / "skill-map"
SKILL_DIR = PACK / ".claude" / "skills" / "harness-mapping"
RUNNER = REPO / "scripts" / "skill_map_scan.py"
WORKFLOW = REPO / ".github" / "workflows" / "pr-decision-diagram.yml"

# Every verb family that reaches skill-map's LLM job queue. Spelled out here
# rather than imported so the test fails if the module's own constant is
# weakened — importing it would make this assertion circular.
PROBABILISTIC = ("jobs", "agent", "findings", "refresh")


# ---------------------------------------------------------------------------
# The no-LLM guarantee
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verb", PROBABILISTIC)
def test_probabilistic_verbs_are_not_on_the_allowlist(verb):
    assert verb not in sms.DETERMINISTIC_VERBS
    assert verb in sms.PROBABILISTIC_VERBS


@pytest.mark.parametrize("verb", PROBABILISTIC)
def test_runner_refuses_probabilistic_verbs(verb, tmp_path):
    """The guard raises rather than warns; a bypassable guard proves nothing."""
    with pytest.raises(ValueError, match="probabilistic|allowlist"):
        sms._run_sm(verb, cwd=tmp_path)


def test_runner_refuses_unknown_verbs(tmp_path):
    with pytest.raises(ValueError, match="allowlist"):
        sms._run_sm("definitely-not-a-verb", cwd=tmp_path)


def test_scan_env_disables_telemetry_and_update_checks():
    env = sms._sm_env()
    assert env["SKILL_MAP_TELEMETRY"] == "0"
    assert env["SM_NO_UPDATE_CHECK"] == "1"
    assert env["NO_COLOR"] == "1"


def test_cli_version_is_pinned():
    """An unpinned upgrade would move the finding counts with no diff to read."""
    assert sms.PINNED_VERSION.count(".") == 2
    manifest = json.loads((PACK / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["upstream"]["pinnedVersion"] == sms.PINNED_VERSION


def test_pack_documents_no_llm_requirement():
    manifest = json.loads((PACK / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["portability"]["requiresLlm"] is False
    assert manifest["portability"]["requiresApiKey"] is False


_PROHIBITION = ("do not", "never", "out of scope", "bypass", "reject", "excluded", "absent")


@pytest.mark.parametrize("verb", PROBABILISTIC)
def test_pack_docs_never_instruct_a_probabilistic_verb(verb):
    """A doc that says `sm jobs submit` is an instruction to break the property.

    These verb names legitimately appear in the pack — naming what is forbidden
    is how the boundary gets documented. So the assertion is that each mention
    sits in prohibiting context, judged over a short window rather than the one
    line, because the prohibition is usually the heading above it.
    """
    for md in PACK.rglob("*.md"):
        lines = md.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if f"sm {verb}" not in line:
                continue
            window = " ".join(lines[max(0, i - 4):i + 2]).lower()
            assert any(marker in window for marker in _PROHIBITION), (
                f"{md.relative_to(REPO)}:{i + 1} appears to instruct "
                f"`sm {verb}`: {line.strip()!r}"
            )


# ---------------------------------------------------------------------------
# Pack shape
# ---------------------------------------------------------------------------

def test_pack_has_required_assets():
    assert (PACK / ".claude-plugin" / "plugin.json").is_file()
    assert (PACK / "README.md").is_file()
    assert (SKILL_DIR / "SKILL.md").is_file()
    assert (PACK / ".claude" / "commands" / "skill-map.md").is_file()
    assert (PACK / ".claude" / "rules" / "skill-map-rules.md").is_file()
    assert RUNNER.is_file()


def test_skill_frontmatter_parses_as_yaml():
    """The analyzer this pack ships exists to catch exactly this failure."""
    yaml = pytest.importorskip("yaml")
    for md in (SKILL_DIR / "SKILL.md", PACK / ".claude" / "commands" / "skill-map.md"):
        text = md.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{md.name} has no frontmatter"
        block = text.split("---\n", 2)[1]
        meta = yaml.safe_load(block)
        assert meta["name"], f"{md.name} declares no name"
        assert meta["description"], f"{md.name} declares no description"


def test_activation_tolerates_a_pack_without_agents():
    """skill-map ships no agents/; activation must not abort under `set -e`."""
    assert not (PACK / ".claude" / "agents").exists()
    proc = subprocess.run(
        ["bash", str(REPO / "scripts" / "activate_skill_stack.sh"), "skill-map"],
        capture_output=True, text=True, timeout=120, cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stderr
    assert (REPO / ".claude" / "skills" / "harness-mapping" / "SKILL.md").is_file()


def test_pack_is_covered_by_the_portability_check():
    text = (REPO / "scripts" / "marketplace_portability_check.sh").read_text(encoding="utf-8")
    assert "skill-packs/skill-map" in text


# ---------------------------------------------------------------------------
# The nested Harness subgraph
# ---------------------------------------------------------------------------

SUMMARY = {
    "nodes": 254,
    "kinds": {"markdown": 170, "command": 37, "skill": 37, "agent": 10},
    "by_analyzer": {
        "error:reference-broken": 51,
        "error:name-collision": 1,
        "warn:frontmatter-parse-error": 2,
        "warn:name-reserved": 17,
    },
}

UNAVAILABLE = {"available": False, "reason": "graph not built"}


def _mermaid(changed, summary=SUMMARY, impact=None):
    return "\n".join(
        pdd.render_mermaid(impact or dict(UNAVAILABLE), "42", "feat/x", summary, changed)
    )


def test_harness_files_detects_both_trees():
    changed = [
        ".claude/skills/skill-map/SKILL.md",
        "skill-packs/skill-map/README.md",
        "scripts/skill_map_scan.py",
        "docs/INTEGRATIONS.md",
    ]
    assert pdd.harness_files(changed) == changed[:2]


def test_subgraph_is_drawn_when_a_harness_file_changes():
    out = _mermaid([".claude/skills/skill-map/SKILL.md"])
    assert "subgraph HARNESS[" in out
    assert "subgraph HKINDS[" in out
    assert "subgraph HISSUES[" in out


def test_subgraph_is_absent_for_a_code_only_pr():
    """Drawn on every PR it would be identical by construction, and so useless."""
    assert "HARNESS" not in _mermaid(["scripts/skill_map_scan.py", "tests/test_x.py"])


def test_subgraph_is_absent_when_the_scan_did_not_run():
    assert "HARNESS" not in _mermaid([".claude/skills/x/SKILL.md"], summary=None)


def test_subgraph_counts_only_dispatchable_entry_kinds():
    """170 markdown nodes would bury the three numbers a reviewer wants."""
    out = _mermaid([".claude/skills/x/SKILL.md"])
    assert "markdown" not in out
    for kind in ("skill", "command", "agent"):
        assert f'"{kind}<br/>' in out


def test_findings_order_puts_collisions_above_broken_references():
    out = _mermaid([".claude/skills/x/SKILL.md"])
    assert out.index("name-collision") < out.index("reference-broken")


def test_warn_severity_findings_still_render():
    """frontmatter-parse-error is a `warn` upstream and still breaks loading."""
    assert "frontmatter-parse-error" in _mermaid([".claude/skills/x/SKILL.md"])


def test_clean_harness_renders_a_no_findings_box():
    summary = {"kinds": {"skill": 3}, "by_analyzer": {"warn:name-reserved": 2}}
    out = _mermaid([".claude/skills/x/SKILL.md"], summary=summary)
    assert "No structural findings" in out


def test_mermaid_subgraphs_are_balanced():
    """An unbalanced subgraph/end pair makes GitHub render nothing at all."""
    impact = {
        "available": True,
        "changed": [(".claude/skills/x/SKILL.md", ["a"])],
        "dependents": [], "dependencies": [], "internal": [], "dropped": 0,
    }
    body = _mermaid([".claude/skills/x/SKILL.md"], impact=impact)
    opens = sum(1 for ln in body.splitlines() if ln.strip().startswith("subgraph "))
    closes = sum(1 for ln in body.splitlines() if ln.strip() == "end")
    assert opens == closes == 4  # CHANGED, HARNESS, HKINDS, HISSUES


def test_load_skill_map_survives_a_missing_or_corrupt_file(tmp_path):
    assert pdd.load_skill_map(None) is None
    assert pdd.load_skill_map(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert pdd.load_skill_map(bad) is None
    listy = tmp_path / "list.json"
    listy.write_text("[1, 2]", encoding="utf-8")
    assert pdd.load_skill_map(listy) is None


# ---------------------------------------------------------------------------
# Summarising and the gate budget
# ---------------------------------------------------------------------------

def test_gate_budget_ignores_broken_references():
    """tests/test_docs_links.py owns those, and is stricter and less noisy."""
    result = {
        "nodes": [{"kind": "skill"}],
        "links": [],
        "issues": [
            {"severity": "error", "analyzerId": "reference-broken"},
            {"severity": "error", "analyzerId": "reference-broken"},
            {"severity": "error", "analyzerId": "name-collision"},
            {"severity": "warn", "analyzerId": "frontmatter-parse-error"},
        ],
    }
    summary = sms.summarize(result)
    assert summary["errors"] == 3
    assert summary["gate_findings"] == 2  # collision + parse error, not the refs
    assert "reference-broken" not in sms.GATE_ANALYZERS


def test_check_exits_nonzero_only_over_budget(monkeypatch, tmp_path):
    result = {
        "nodes": [], "links": [],
        "issues": [{"severity": "error", "analyzerId": "name-collision"}] * 2,
    }
    monkeypatch.setattr(sms, "scan", lambda root, timeout=600: result)
    within = sms.main(["--root", str(tmp_path), "--check", "--max-errors", "2"])
    over = sms.main(["--root", str(tmp_path), "--check", "--max-errors", "1"])
    assert within == sms.EXIT_OK
    assert over == sms.EXIT_ISSUES


def test_missing_cli_reports_unavailable_not_failure(monkeypatch, tmp_path):
    """A runner without Node must not turn a repository check red."""
    def boom(root, timeout=600):
        raise sms.SkillMapUnavailable("no sm and no npx")
    monkeypatch.setattr(sms, "scan", boom)
    assert sms.main(["--root", str(tmp_path), "--summary"]) == sms.EXIT_UNAVAILABLE


def test_sm_command_prefers_installed_binary_over_npx(monkeypatch, tmp_path):
    binary = tmp_path / "sm"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("SKILL_MAP_BIN", str(binary))
    assert sms._sm_command() == [str(binary)]

    monkeypatch.delenv("SKILL_MAP_BIN")
    monkeypatch.setattr(sms.shutil, "which", lambda name: "/usr/bin/sm" if name == "sm" else None)
    assert sms._sm_command() == ["/usr/bin/sm"]


def test_sm_command_raises_when_nothing_resolves(monkeypatch):
    monkeypatch.delenv("SKILL_MAP_BIN", raising=False)
    monkeypatch.setattr(sms.shutil, "which", lambda name: None)
    with pytest.raises(sms.SkillMapUnavailable):
        sms._sm_command()


def test_npx_fallback_pins_the_version(monkeypatch):
    monkeypatch.delenv("SKILL_MAP_BIN", raising=False)
    monkeypatch.setattr(
        sms.shutil, "which", lambda name: "/usr/bin/npx" if name == "npx" else None
    )
    assert sms._sm_command() == ["/usr/bin/npx", "-y", f"@skill-map/cli@{sms.PINNED_VERSION}"]


# ---------------------------------------------------------------------------
# CI wiring
# ---------------------------------------------------------------------------

def test_workflow_records_a_skill_map_gate_and_feeds_the_diagram():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "skill_map_scan.py" in text
    assert 'record "skill map"' in text
    assert "--skill-map" in text


def test_workflow_treats_an_unavailable_scanner_as_a_skip():
    """Exit 3 must land on the skip branch, never on fail."""
    text = WORKFLOW.read_text(encoding="utf-8")
    gate = text.split('record "skill map"', 1)[1]
    assert "skip" in gate.split("esac", 1)[0]


def test_scan_output_is_captured_via_a_file_not_a_pipe():
    """Node truncates piped stdout at the OS pipe buffer when it exits early."""
    source = RUNNER.read_text(encoding="utf-8")
    assert "stdout_path" in source
    assert "tempfile" in source
