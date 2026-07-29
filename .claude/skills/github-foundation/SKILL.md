---
name: github-foundation
description: Shared repository operations foundation for all domain packs: git discipline, CI hygiene, review workflow, graph snapshots, and memory sync.
---

# GitHub Foundation Skill

Use this as the common layer for every domain skill stack.

## Core responsibilities

- Enforce clean branching and commit hygiene.
- Keep CI workflows fast and deterministic.
- Ensure review and ship commands remain consistent.
- Persist operational memory and graph snapshots after meaningful changes.
- Keep PRs easy to review by separating mechanical and behavioral changes.
- Keep GitHub Actions guidance grounded in official docs links.

## Shared command paths

- `.claude/commands/git-standard.sh`
- `.claude/commands/review.md`
- `.claude/commands/ship.md`
- `.claude/commands/update-memory.sh`
- `.claude/commands/lint-and-graph.sh`

## Shared review conventions

- Findings must include file/line evidence when possible.
- Prefer concise, actionable comments: problem first, then fix.
- Distinguish severity: bug, risk, nit, question.
- Avoid style-only noise when there is no concrete impact.

## Shared safety conventions

- Do not run destructive git commands unless explicitly requested.
- Do not force-push protected branches.
- Do not bypass hooks unless explicitly requested.
- Do not include secrets in commits.

## Rules

Follow `.claude/rules/standards.md` in all packs.
