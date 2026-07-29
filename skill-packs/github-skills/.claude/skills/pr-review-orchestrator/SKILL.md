---
name: pr-review-orchestrator
description: Run a structured PR or pre-push review across branch, working, staged, or all scopes and return high-signal findings.
---

# PR Review Orchestrator

Use when asked to review a PR, branch, staged set, or uncommitted work.

## Scope model

- `branch`: committed branch changes vs base.
- `working`: uncommitted vs `HEAD`.
- `staged`: staged diff vs `HEAD`.
- `all`: branch + uncommitted.

## Workflow

1. Capture scope and diff stats.
2. Stop early on empty diffs.
3. Flag overly large diffs and suggest splitting.
4. Classify findings by severity:
   - `critical`, `high`, `medium`, `low`.
5. Report findings with evidence and concrete next steps.

## Required output fields

- file/location
- severity
- confidence
- issue statement
- recommendation

## Guardrails

- Review only; do not auto-apply fixes unless explicitly requested.
- Prefer behavior/risk findings over formatting noise.
