# dbt model naming patterns for Enhanza

The Enhanza repository uses a strict naming pattern that should be mirrored in this use case package.

## Naming rules

- Model files should be lowercase, plural, and snake_case.
- The preferred shape is `{datasource}_{stage}_{dim/fact}_{name}.sql`.
- The business layer should favor humanized names such as `fact_sales` over raw technical names.

## Example patterns

| Layer | Example file | Purpose |
|---|---|---|
| BI | `fortnox_bi_fact_invoices.sql` | source-aligned fact building block |
| BI | `fortnox_bi_dim_articles.sql` | source-aligned dimension building block |
| Unified | `erp_unified_fact_sales.sql` | cross-source business fact |
| Logic | `fact_sales.sql` | business-friendly fact for downstream consumers |
| Logic | `dim_customer.sql` | conformed customer dimension |
| Logic | `dim_company.sql` | tenant or organization dimension |

## Column conventions

- Use PascalCase for business-facing columns.
- Keep primary and foreign keys as STRING values.
- Follow the Enhanza convention of naming keys as `{Singular}Id` and prefixing with `OrgId || '-' ||` except for `dim_company`.

## Layering guidance

- Keep BI models as source-aligned building blocks.
- Use unified models to combine multiple sources into one logical representation.
- Reserve the logic layer for humanized, business-ready definitions used by downstream reporting and Cube.
