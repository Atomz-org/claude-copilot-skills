# github-skills (shared foundation)

This pack contains the common GitHub/repository automation layer that can be reused by all domain packs.

Contents:

- `.claude/commands/`: infra command set (git standards, sync, review, memory, graph snapshot)
- `.claude/agents/`: meta agents (`repo-maintainer`, `skill-author`, `submodule-integrator`)
- `.claude/rules/standards.md`: repository and workflow standards
- `.claude/skills/github-foundation/SKILL.md`: shared operating guidance
- `.claude/skills/github-actions-docs-grounded/`: docs-first GitHub Actions guidance
- `.claude/skills/git-commit-quality/`: diff-aware Conventional Commit workflow
- `.claude/skills/pr-review-orchestrator/`: structured multi-scope PR review flow
- `.claude/skills/pr-review-terse-comments/`: high-signal one-line review comment style
- `.claude/skills/pr-reviewability-prep/`: prep a PR to be easier to review

Use this pack as the always-on base for any domain bundle (dbt, senior-data-scientist, principal-data-engineer, and future packs).

## Design intent

- Keep this pack domain-agnostic so all future packs can reuse it.
- Prefer deterministic checks over prose-only guidance.
- Keep review output actionable: location, impact, and fix.
