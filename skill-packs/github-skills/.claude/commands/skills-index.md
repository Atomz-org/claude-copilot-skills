---
description: Show a quick index of shared github-skills capabilities by intent.
---

# Shared GitHub Skills Index

Use this index to find the right playbook fast.

## Commit intent

- `git-commit-quality` skill
- `git-standard.sh` command (supports `--dry-run`)
- `git-guardrails-claude-code` skill
- `setup-git-guardrails.md` command

## Review intent

- `pr-review-orchestrator` skill
- `pr-review-terse-comments` skill
- `pr-reviewability-prep` skill
- `review.md` command
- `pr-ready.md` command

## Merge intent

- `github-pr-merge-ceremony` skill
- `pr-merge.md` command
- `ship.md` command

## Branching intent

- `git-flow-branch-planner` skill
- `branch-plan.md` command

## Docs intent

- `github-actions-docs-grounded` skill
- `documentation-writer-diataxis` skill
- `architecture-page` skill — hand-drawn architecture pages under `public/`, figures pinned
  to committed artifacts
- `write-docs.md` command
- `architecture.md` command

## Conflicts intent

- `resolve-merge-conflicts` skill
- `resolve-conflicts.md` command

## Data onboarding intent

- `new-use-case` command — frame a request before any model exists
- `new-connector` command → `connector-onboarding` skill — onboard a source system into an
  existing use-case, then commit through `git-standard.sh`
- `scripts/new_connector.py` (detects the target project's conventions; `--dry-run` first)

## Foundation and operations

- `github-foundation` skill
- `marketplace-portability-patterns` skill
- `update-memory.sh` command
- `lint-and-graph.sh` command
- `sync-submodule.md` command
- `focused-fix.md` command
- `marketplace-portability.md` command
- `scripts/sync_context.sh` (RTK + Graphify + AgentMemory sync)

## Recommended workflow

1. Identify intent using this index.
2. Run the corresponding command playbook.
3. Apply command output and verify checks.
4. Use `ship.md` before merge.
