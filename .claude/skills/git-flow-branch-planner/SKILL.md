---
name: git-flow-branch-planner
description: Analyze local changes and recommend or create a Git Flow style branch with safe naming and edge-case handling.
---

# Git Flow Branch Planner

Use this skill to classify work into a branch type and generate a semantic branch name.

## Branch classes

- `feature/<name>` for new capabilities and non-critical improvements.
- `release-<x.y.z>` for release prep and version finalization.
- `hotfix/<name>` or `hotfix-<x.y.z>` for urgent production fixes.

## Workflow

1. Inspect changes with `git status` and `git diff` (or `git diff --cached`).
2. Classify urgency and impact.
3. Recommend branch type and 2-3 branch-name options.
4. Check for branch-name conflicts locally/remotely.
5. Create branch only after explicit confirmation.

## Guardrails

- If changes are mixed and unrelated, recommend splitting.
- If no changes are present, stop and explain.
- Do not auto-create from the wrong base branch.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/branch-plan` | A classification of the working tree plus 2-3 name options; no branch is created until you confirm |
| "I'm on main and started editing — fix this" | A branch recommendation and the safe move-my-work-across sequence |
| "is this a hotfix or a feature?" | The classification with its reasoning, and the naming form that follows from it |

**Worked example**

> `/branch-plan`

```
Changed : src/checkout/tax.ts, tests/tax.test.ts   (2 files, +84 −11)
Class   : feature — new VAT rounding rule, no production incident open
Base    : main (clean, up to date)

Options
  1. feature/CHK-412-vat-rounding      ← recommended, matches <type>/<ticket>-<description>
  2. feature/CHK-412-checkout-tax
  3. feature/no-ticket-vat-rounding    ← only if CHK-412 is not the right ticket

No local or origin ref conflicts. Create option 1?
```

If the diff had also touched an unrelated logging change, the answer is "split first" — say
so instead of naming a branch that covers two things.
