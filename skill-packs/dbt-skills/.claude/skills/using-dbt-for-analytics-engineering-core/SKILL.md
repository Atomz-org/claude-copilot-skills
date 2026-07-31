---
name: using-dbt-for-analytics-engineering-core
description: Build and modify dbt models using dbt Core best practices, source contracts, tests, and artifact-driven validation.
---

# Using dbt for Analytics Engineering (Core)

## Workflow

1. Frame request and define grain.
2. Validate source assumptions from existing docs and artifacts.
3. Design or extend models using `ref()` and `source()` only.
4. Run `dbt build --select <model>+`.
5. Add tests and documentation before merge.

## Must-do checks

- No hardcoded table names.
- Primary keys must have `unique` and `not_null` tests.
- Logic-heavy models must include unit tests.
- Breaking changes must include contracts/versioning updates.

## Helpful scripts

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model <model> --direction down --mermaid
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
```

## dbt Core translation notes

- Replace hosted lineage/exposure checks with local manifest analysis and dependency scripts.
- Treat artifact validation as required for every merge decision.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "add a refund column to fct_orders" | The grain checked first — refunds are often 1:N to orders, which silently fans out the totals |
| "is this model ready to merge?" | The auditor run, PK tests confirmed, downstream impact listed |
| "select from raw.shopify.orders" | A rewrite through `source()`; a hardcoded table breaks lineage, `--select`, and state comparison |

**Worked example**

> "add refund_amount to fct_orders"

```bash
# 1. Grain first. One row per order — is refunds 1:1?
dbt show --select stg_shopify__refunds --limit 20
#   order_id 4471 appears 3 times → 1:N. A join here multiplies every order row.
#   → aggregate refunds to order grain in int_refunds_by_order, then join 1:1.

# 2. Build the path, not the whole project
dbt build --select int_refunds_by_order+ 

# 3. Prove the grain held
dbt test --select fct_orders            # unique + not_null on order_id must still pass

# 4. Artifact checks before merge
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
    --model fct_orders --direction down --mermaid
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

Step 1 is the whole job. Joining refunds directly would pass every existing test while
tripling revenue for any order refunded twice.
