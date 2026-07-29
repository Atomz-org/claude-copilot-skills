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
