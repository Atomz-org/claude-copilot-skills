---
name: building-dbt-semantic-layer-core
description: Define semantic models and metrics using dbt Core-compatible YAML and local validation loops.
---

# Building dbt Semantic Layer (Core)

## Determine spec

- dbt Core 1.12+ may use latest semantic-model YAML style.
- dbt Core 1.6-1.11 should use legacy `semantic_models` and `metrics` style.

## Validation loop

```bash
dbt parse
mf validate-configs
```

If `mf` is not available, ensure syntax and references are parse-clean and document follow-up validation requirement.

## Checklist

- One primary entity per semantic model grain.
- Time dimension and granularity declared.
- Metric type documented (`simple`, `derived`, `cumulative`, `ratio`, `conversion`).
- Filters only reference declared entities/dimensions.

## dbt Core translation notes

- Cloud semantic APIs are optional and out of scope for this repository baseline.
- Use YAML + local parse/MetricFlow validation for reproducibility.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "define net revenue as a metric" | The YAML in the style your dbt version accepts, then the local validation loop run |
| `/dbt-semantic gross margin` | Semantic model over the mart, metric definition, `mf validate-configs`, and a sanity query |
| "mf validate-configs is failing" | Usually a missing time-dimension `granularity` — checked first |

**Worked example**

> "define average order value"

```yaml
semantic_models:
  - name: orders
    model: ref('fct_orders')
    defaults:
      agg_time_dimension: ordered_at
    entities:
      - {name: order, type: primary, expr: order_id}
      - {name: customer, type: foreign, expr: customer_id}
    dimensions:
      - name: ordered_at
        type: time
        type_params: {time_granularity: day}   # omitting this is the usual failure
    measures:
      - {name: order_total, agg: sum, expr: total_amount}
      - {name: order_count, agg: count, expr: order_id}

metrics:
  - name: average_order_value
    type: ratio                                 # not a stored column — a ratio metric
    type_params:
      numerator: order_total
      denominator: order_count
```

```bash
dbt parse && mf validate-configs
mf query --metrics average_order_value --group-by metric_time__month
```

Eyeball the result against a known-good SQL query before anyone builds a dashboard on it.
Storing AOV as a column in the mart instead would double-count on every rollup.
