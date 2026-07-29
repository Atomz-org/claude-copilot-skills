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
