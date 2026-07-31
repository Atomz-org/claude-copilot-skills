---
name: github-pr-merge-ceremony
description: Enforce a pre-merge checklist for GitHub pull requests before running gh pr merge.
---

# GitHub PR Merge Ceremony

Use this skill for controlled PR merging.

## Pre-merge checklist

- review comments addressed or acknowledged.
- required checks green.
- tests and lint pass.
- changelog updated when behavior changed.
- milestone reviewed (warning if missing, not hard block unless policy says so).

## Merge policy

- Show checklist summary and ask for confirmation.
- Prefer merge commit strategy unless repository policy differs.
- Delete only short-lived topic branches; never delete long-lived integration branches.

## Post-merge

- Sync local base branch.
- Report merge result and follow-up actions.

## Guardrails

- Never merge if required checks fail.
- Never proceed without user confirmation.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/pr-merge 128` | The checklist evaluated against PR 128, then a confirmation prompt — never an immediate merge |
| "is 128 ready to merge?" | The same checklist, reported without offering to merge |
| "merge it" with a red check | A refusal naming the failing check, and what to do about it |

**Worked example**

> `/pr-merge 128`

```
PR #128 — fix(checkout): round VAT once at the order total   (feature/CHK-412 → main)

  ✓ review comments   2 threads, both resolved
  ✓ required checks   ci / test, ci / lint — passing
  ✓ tests and lint    green on 1748974
  ✓ changelog         CHANGELOG.md updated (behavior changed)
  ⚠ milestone         none set — warning only

Strategy      : merge commit (repository default)
Branch cleanup: delete feature/CHK-412-vat-rounding — short-lived topic branch
Post-merge    : git checkout main && git pull

Merge #128 now?
```

With `ci / test` failing, the answer is a stop, not a checklist with one red row and a
merge prompt underneath it.
