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
        ".claude/commands/skills-index.md",
        ".claude/commands/branch-plan.md",
        ".claude/commands/pr-merge.md",
        ".claude/commands/setup-pre-commit.md",
        ".claude/commands/resolve-conflicts.md",
        ".claude/commands/write-docs.md",
        ".claude/commands/setup-git-guardrails.md",
        ".claude/commands/review.md",
        ".claude/commands/ship.md",
        ".claude/commands/sync-submodule.md",
        ".claude/hooks/block-dangerous-git.sh",
        ".claude/skills/git-flow-branch-planner/SKILL.md",
        ".claude/skills/github-pr-merge-ceremony/SKILL.md",
        ".claude/skills/setup-pre-commit-hooks/SKILL.md",
        ".claude/skills/resolve-merge-conflicts/SKILL.md",
        ".claude/skills/documentation-writer-diataxis/SKILL.md",
        ".claude/skills/git-guardrails-claude-code/SKILL.md",
        ".claude/agents/repo-maintainer.md",
        ".claude/agents/skill-author.md",
        ".claude/agents/submodule-integrator.md",
        "skill-packs/github-skills/.claude/commands/skills-index.md",
        "skill-packs/github-skills/.claude/commands/setup-git-guardrails.md",
        "skill-packs/github-skills/.claude/hooks/block-dangerous-git.sh",
        "skill-packs/github-skills/.claude/skills/git-flow-branch-planner/SKILL.md",
        "skill-packs/github-skills/.claude/skills/github-pr-merge-ceremony/SKILL.md",
        "skill-packs/github-skills/.claude/skills/setup-pre-commit-hooks/SKILL.md",
        "skill-packs/github-skills/.claude/skills/resolve-merge-conflicts/SKILL.md",
        "skill-packs/github-skills/.claude/skills/documentation-writer-diataxis/SKILL.md",
        "skill-packs/github-skills/.claude/skills/git-guardrails-claude-code/SKILL.md",
        "skill-packs/dbt-skills/use-cases/.gitkeep",
        "skill-packs/github-skills/use-cases/.gitkeep",
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


def test_skills_index_covers_all_primary_git_intents():
    index_doc = (REPO_ROOT / ".claude/commands/skills-index.md").read_text(encoding="utf-8").lower()

    assert "commit" in index_doc
    assert "review" in index_doc
    assert "merge" in index_doc
    assert "branch" in index_doc
    assert "docs" in index_doc
    assert "conflict" in index_doc


def test_copilot_instructions_enforce_ai_core_and_guardrails():
    copilot_doc = (REPO_ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8").lower()

    assert "rtk" in copilot_doc
    assert "graphify" in copilot_doc
    assert "agentmemory" in copilot_doc
    assert "scripts/sync_context.sh" in copilot_doc
    assert "block-dangerous-git.sh" in copilot_doc


def test_dbt_usecases_are_pack_local():
    dbt_agent = (REPO_ROOT / "skill-packs/dbt-skills/.claude/agents/senior-analytics-engineer.md").read_text(encoding="utf-8")
    dbt_rules = (REPO_ROOT / "skill-packs/dbt-skills/.claude/rules/analytics-engineering-rules.md").read_text(encoding="utf-8")

    assert "skill-packs/dbt-skills/use-cases/<slug>/" in dbt_agent
    assert "skill-packs/dbt-skills/use-cases/<slug>/use-case-spec.md" in dbt_rules
