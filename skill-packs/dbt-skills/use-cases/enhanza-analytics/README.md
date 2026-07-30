# Enhanza Analytics use case

This package turns the external Enhanza Analytics repository into a reusable dbt use case for this repository.
It is tailored to the documented Enhanza flow:

- raw API data into BigQuery
- dbt for BI, unified, and logic modeling
- Cube for governed semantic metrics exposed to app.enhanza.com

## What is included

- [use-case-spec.md](use-case-spec.md) — a framed analytics use case with delivery and quality gates
- [dbt-model-patterns.md](dbt-model-patterns.md) — example dbt model names and layer conventions
- [source-conventions.md](source-conventions.md) — source naming and staging guidance for BigQuery-based projects
- [cube-metric-guidance.md](cube-metric-guidance.md) — Cube metric guidance for app-facing analytics
- [skills/enhanza-business-logic/SKILL.md](skills/enhanza-business-logic/SKILL.md) — a business-specific skill for this domain
- [skills/enhanza-dbt-skill/SKILL.md](skills/enhanza-dbt-skill/SKILL.md) — dbt implementation guidance for this use case

## Local dbt project

The use case now contains the canonical imported Enhanza project under [dbt_project/](dbt_project/), including the preserved package structure at [dbt_project/ported_package/](dbt_project/ported_package/).

A separate fast validation path exists under [local_run_project/](local_run_project/) for DuckDB-based experimentation and quick model validation. Use this path for quick experiments, local proof-of-concept changes, and fast feedback before applying them to the canonical `dbt_project/` implementation.

The active compact local project uses a simple Enhanza-style mart built around five sample orders and a three-layer structure:

- staging model: [dbt_project/models/staging/stg_sales_orders.sql](dbt_project/models/staging/stg_sales_orders.sql)
- logic models: [dbt_project/models/logic/dim_customers.sql](dbt_project/models/logic/dim_customers.sql), [dbt_project/models/logic/fact_orders.sql](dbt_project/models/logic/fact_orders.sql)
- semantic model: [dbt_project/models/semantic/orders_mart.sql](dbt_project/models/semantic/orders_mart.sql)
- schema and singular tests under [dbt_project/models/staging/schema.yml](dbt_project/models/staging/schema.yml), [dbt_project/models/logic/schema.yml](dbt_project/models/logic/schema.yml), [dbt_project/models/semantic/schema.yml](dbt_project/models/semantic/schema.yml), and [dbt_project/tests/test_orders_mart.sql](dbt_project/tests/test_orders_mart.sql)

## Validation

The local dbt project was validated end to end with dbt + DuckDB.
Verified result: PASS=15 WARN=0 ERROR=0 SKIP=0.
