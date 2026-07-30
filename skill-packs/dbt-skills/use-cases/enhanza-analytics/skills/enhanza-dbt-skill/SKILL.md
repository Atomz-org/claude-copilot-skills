name: enhanza-dbt-skill
description: Enhanza Analytics dbt implementation guidance for adding models, connectors, and refining the imported Enhanza dbt project.

# Enhanza dbt Skill

Use this skill when working on the Enhanza Analytics use case’s dbt implementation.
It is the dbt-specific companion to `enhanza-business-logic` and focuses on modeling, source contracts, and project hygiene.

## What to keep in mind

- The canonical imported project is `dbt_project/`.
- Keep raw API source handling in `dbt_project/models/staging/`.
- Keep source-aligned BI/unified logic in `dbt_project/models/logic_bi/`.
- Keep app-facing exposures in `dbt_project/models/app/`.
- Use `source()` and `ref()` only; do not hardcode external dataset names.
- Validate with `dbt build`, not `dbt run` + `dbt test`.
- Use `local_run_project/` for fast DuckDB validation before changing the full project.

## Working pattern

1. Review `use-case-spec.md`, `source-conventions.md`, and `dbt-model-patterns.md`.
2. Add new source definitions in `dbt_project/models/sources.yml`.
3. Build staging models in `dbt_project/models/staging/<source>/`.
4. Add reusable logic/BI models in `dbt_project/models/logic_bi/`.
5. Add final app-level exposures in `dbt_project/models/app/`.
6. Add tests, descriptions, and contracts to `dbt_project/models/schema.yml` and `dbt_project/models/sources.yml`.
7. Run `dbt build` from `skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/`.

## Good defaults

- Use business-friendly names like `fact_sales`, `dim_customers`, and `orders_mart`.
- Keep staging as the only raw-to-clean layer.
- Prefer `view` materialization for staging and logic-building models unless there is a measured reason to use `table`.
- Add `unique`, `not_null`, and `relationships` tests for every new model.
- Preserve traceability so Cube metrics can be traced back to the logic layer.

## How to use this skill

1. Open the Enhanza use-case folder and read the current use-case spec and source conventions.
2. Identify the new source, model, or connector work as either staging, BI/unified logic, or app exposure.
3. Use the existing `dbt_project/` layout as the authoritative project structure.
4. Keep the `local_run_project/` path as a quick validation environment for new model ideas.
5. When in doubt, add a small schema test and a source contract before shipping the change.
