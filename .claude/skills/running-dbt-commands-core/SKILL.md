---
name: running-dbt-commands-core
description: Run dbt Core commands safely with selectors, strict no-node checks, and artifact-aware validation.
---

# Running dbt Commands (Core)

## Rules

- Prefer `dbt build` over run-then-test for development and CI.
- Always use `--select`.
- Add `--warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'` in CI-safe flows.

## Standard patterns

```bash
dbt ls --select "<selector>"
dbt build --select "<selector>" --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'
dbt test --select "<selector>"
dbt show --select "<model>" --limit 20
```

## Artifact checks

After command runs, inspect artifacts:

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json --manifest target/manifest.json
python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9
```

## dbt Core translation notes

- If upstream guidance suggests Cloud/Fusion APIs, translate to local Core command + artifact review.
- Use `--state` and `--defer` only when production artifacts are available locally.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "rebuild everything downstream of stg_shopify__orders" | `dbt ls` first to show the scope, then the build once you have seen it |
| `/dbt-build` | The selector, the acceptance bar, and the cost — agreed before anything runs |
| "my selector matched nothing" | The `NoNodesForSelectionCriteria` cause, which passes silently without the warn-error flag |

**Worked example**

> "I changed stg_shopify__orders — rebuild what it affects"

```bash
# 1. See the scope before spending warehouse time on it
dbt ls --select stg_shopify__orders+ --output name
#   stg_shopify__orders
#   int_orders_categorized
#   fct_orders
#   dim_customer_orders          ← the one people forget is downstream

# 2. Build it, failing loudly if the selector matches nothing
dbt build --select stg_shopify__orders+ \
    --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'

# 3. Read the artifacts rather than the scroll-back
python scripts/run_results_analyzer.py \
    --run-results target/run_results.json --manifest target/manifest.json
python scripts/test_coverage_reporter.py \
    --manifest target/manifest.json --layer marts --min-coverage 0.9
```

Without the `--warn-error-options` flag, a typo in the selector exits 0 having built
nothing — which reads as a green CI run.
