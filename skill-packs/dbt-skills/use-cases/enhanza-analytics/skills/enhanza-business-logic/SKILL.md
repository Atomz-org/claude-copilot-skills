---
name: enhanza-business-logic
description: Business-specific guidance for modeling Enhanza's dbt logic layer and Cube semantic metrics for app-facing analytics.
---

# Enhanza Business Logic Skill

Use this skill when working on the Enhanza Analytics use case in this repository.
It translates the external project’s workflow into a dbt-oriented operating pattern for this pack.

## What to keep in mind

- Follow the documented pipeline stages: raw API data → BigQuery → dbt BI/unified/logic models → Cube semantic layer → app experience.
- Treat the organization or tenant context as a first-class security and join key.
- Keep business definitions in the dbt logic layer; use Cube for governed metrics and access-controlled aggregation.
- Prefer reusable logic models for business facts and dimensions, then expose the final metric through the semantic layer.
- Preserve traceability from a metric back to its source model and the business definition.

## Working pattern

1. Start from the use-case spec and the external Enhanza repository docs.
2. Map the data to the correct pipeline stage before writing SQL.
3. Build dbt models for BI, unified, and logic layers, then expose them through Cube metrics.
4. Validate the output with dbt tests, semantic-layer checks, and source freshness checks before shipping.

## Good defaults

- Use `fact_*` and `dim_*` naming where the business concept is source-aligned.
- Keep the logic layer humanized and business-friendly.
- Make row-level security and metric consistency part of the design, not an afterthought.
- If a question is really about how a metric should be defined, prefer a governed metric in Cube over a one-off custom SQL view.
