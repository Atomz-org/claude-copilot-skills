from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_automation_docs_cover_claude_and_copilot_git_workflow():
    setup_doc = (REPO_ROOT / ".github/AUTOMATION_SETUP.md").read_text(encoding="utf-8")
    test_doc = (REPO_ROOT / ".github/AUTOMATION_TEST.md").read_text(encoding="utf-8")

    assert "Claude" in setup_doc
    assert "Copilot" in setup_doc
    assert "branch" in setup_doc.lower()
    assert "commit" in setup_doc.lower()
    assert "Claude" in test_doc
    assert "Copilot" in test_doc


def test_required_agent_commands_and_workflows_exist():
    required_paths = [
        ".claude/commands/git-standard.sh",
        ".claude/commands/review.md",
        ".claude/commands/ship.md",
        ".claude/commands/sync-submodule.md",
        ".claude/agents/repo-maintainer.md",
        ".claude/agents/skill-author.md",
        ".claude/agents/submodule-integrator.md",
        ".github/workflows/ci.yml",
        ".github/workflows/claude-code-review.yml",
        ".github/workflows/pr-issue-auto-close.yml",
        ".github/workflows/smart-sync.yml",
        ".github/workflows/ci-quality-gate.yml",
    ]

    for relative_path in required_paths:
        assert (REPO_ROOT / relative_path).exists(), f"Missing required path: {relative_path}"


def test_workflows_include_expected_git_and_agent_triggers():
    review_workflow = (REPO_ROOT / ".github/workflows/claude-code-review.yml").read_text(encoding="utf-8")
    issue_close_workflow = (REPO_ROOT / ".github/workflows/pr-issue-auto-close.yml").read_text(encoding="utf-8")
    sync_workflow = (REPO_ROOT / ".github/workflows/smart-sync.yml").read_text(encoding="utf-8")
    quality_workflow = (REPO_ROOT / ".github/workflows/ci-quality-gate.yml").read_text(encoding="utf-8")

    assert "pull_request" in review_workflow or "workflow_dispatch" in review_workflow
    assert "pull_request" in issue_close_workflow or "workflow_dispatch" in issue_close_workflow
    assert "status: in-review" in review_workflow or "status: triage" in review_workflow
    assert "status: done" in issue_close_workflow or "gh issue close" in issue_close_workflow
    assert "status: triage" in sync_workflow or "status: done" in sync_workflow
    assert "pytest" in quality_workflow.lower() or "lint" in quality_workflow.lower()
