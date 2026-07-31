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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/review branch` | Committed branch changes vs base, reviewed and ranked by severity |
| `/review staged` | The staged diff only — the usual pre-commit pass |
| "review before I push" | Scope `all`, so uncommitted work is not missed |
| "look at PR 128" | The PR diff pulled with `gh`, then the same review shape |

**Worked example**

> `/review branch`

```
Scope: branch (feature/CHK-412-vat-rounding vs main) — 6 files, +212 −40

critical  src/checkout/tax.ts:88            confidence high
  Rounding applied per line item, then again on the order total. Orders with >3 lines
  drift by up to 2 cents against the ledger.
  → Round once, at the order total. Add a 4-line-item case to tests/tax.test.ts.

medium    src/checkout/tax.ts:12            confidence medium
  VAT_RATE is a module constant; the spec says it varies per region.
  → Take the rate as an argument, or state in the PR why a constant is correct for now.

low       tests/tax.test.ts:44              confidence high
  Test name says "negative amount" but asserts on zero.

Verdict: one blocker. Not ready to merge.
```

An empty diff stops here and says so — it does not produce an empty findings table.
