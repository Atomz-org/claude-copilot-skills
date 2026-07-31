---
name: working-with-dbt-mesh-core
description: Manage model contracts, versions, groups, and access in dbt Core multi-team or multi-project workflows.
---

# Working with dbt Mesh (Core)

## Core practices

- Use contracts on shared models.
- Use model versions for breaking changes.
- Use groups and access controls for ownership boundaries.

## Breaking-change workflow

1. Identify downstream consumers.
2. Add a new model version instead of in-place destructive edits.
3. Keep previous version during migration window.
4. Add contract check in CI.

## Commands

```bash
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model <model> --direction down
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
```

## dbt Core translation notes

- Replace platform governance dashboards with manifest-driven checks and repository CI gates.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "what breaks if I drop this column?" | The downstream list from the manifest, then the version-or-coordinate decision |
| "rename customer_id to customer_key" | On a contracted model: a new version, not an in-place edit |
| "stop people building on this model" | `access: private` plus a group with an owner — enforced at parse time |

**Worked example**

> "fct_orders needs `revenue` renamed to `net_revenue`"

```bash
# 1. Who is on the other side of the change
python scripts/model_dependency_analyzer.py \
    --manifest target/manifest.json --model fct_orders --direction down
#   dim_customer_orders (this project)  → we can fix in the same PR
#   exposure: finance_dashboard         → we cannot; it needs a migration window
```

```yaml
models:
  - name: fct_orders
    latest_version: 2
    access: public
    config: {contract: {enforced: true}}
    columns:
      - {name: order_id, data_type: varchar, constraints: [{type: not_null}]}
      - {name: net_revenue, data_type: numeric(38,2)}
    versions:
      - v: 1
        deprecation_date: 2026-10-01           # the migration window, stated
        columns: [{include: all, exclude: [net_revenue]}, {name: revenue, data_type: numeric(38,2)}]
      - v: 2
```

```bash
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

Consumers stay on `ref('fct_orders', v=1)` until the deprecation date. An in-place rename
would break the finance dashboard at the next production run, with no failing test.
