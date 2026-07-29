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
