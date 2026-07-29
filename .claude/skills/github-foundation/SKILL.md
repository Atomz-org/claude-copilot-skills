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

## Shared command paths

- `.claude/commands/git-standard.sh`
- `.claude/commands/review.md`
- `.claude/commands/ship.md`
- `.claude/commands/update-memory.sh`
- `.claude/commands/lint-and-graph.sh`

## Rules

Follow `.claude/rules/standards.md` in all packs.
