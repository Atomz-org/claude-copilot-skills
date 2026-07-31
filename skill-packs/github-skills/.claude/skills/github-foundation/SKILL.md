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

## Examples

This skill is the layer under the others, so it is usually loaded alongside a task skill
rather than called on its own.

| Ask Claude | What you get |
|---|---|
| `/skills-index` | The intent-to-skill map, so the right focused skill gets loaded instead of this one |
| "take this change from branch to merged" | The full ceremony in order: branch → commit → review → ship → merge → sync |
| "what are the rules here?" | Branching, commit form, review conventions, and safety limits — from `.claude/rules/standards.md`, not from memory |

**Worked example — the full path for one change**

> "I've finished the VAT fix, take it through"

```
1. /branch-plan          → feature/CHK-412-vat-rounding, created after confirmation
2. commit                → fix(checkout): round VAT once at the order total
                           (staged diff read first; no secrets; hooks not skipped)
3. /review branch        → findings with file:line evidence, severity-ranked
4. /pr-ready             → mechanical and behavioral commits split; PR body written
5. /ship                 → checks green, release readiness confirmed
6. /pr-merge 128         → checklist, then confirmation, then merge
7. ./scripts/sync_context.sh "merged CHK-412 VAT rounding"
                         → graph snapshot and memory updated
```

Step 7 is the one that gets skipped. The graph and memory are how the next session starts
oriented instead of re-deriving the same context.
