# Source conventions for Enhanza-style dbt projects

This guidance captures the source-handling pattern implied by the Enhanza repository and makes it reusable for this use case package.

## Source layer expectations

- Treat raw API extracts as source data rather than directly modeling from them in the logic layer.
- Declare sources explicitly and keep staging logic isolated from downstream logic.
- Preserve the business meaning of the source through clear source aliases and consistent column naming.

## Recommended pattern

1. Create a source definition for each upstream table or API extract.
2. Build a staging model that renames and standardizes the columns.
3. Add a BI or unified model for domain shaping.
4. Expose the final business logic through a logic model that is stable for Cube and reporting.

## BigQuery-specific notes

- Keep warehouse-specific behavior explicit in dbt macros and model logic.
- Avoid hard-coding project or dataset names where the same model should be portable across environments.
- Make freshness and contract expectations visible in the source configuration so downstream models can depend on them.

## Source naming

The source name carries an `_api` suffix and resolves to a per-tenant BigQuery dataset:

```sql
{{ source('fortnox_api', 'invoices') }}      -- fortnox_api_<uid>.invoices
{{ source('tripletex_api', 'accounts') }}    -- tripletex_api_<uid>.accounts
```

The suffix is not optional. `source('fortnox', 'invoices')` does not resolve — every entry
in [dbt_project/models/sources.yml](dbt_project/models/sources.yml) is named `<source>_api`,
and the `_demo` variants are `<source>_api_demo`.

There is no `erp` source. `erp_bi_*` is a modeling layer built by unioning each connector's
adapter models, not an upstream system — see [CONNECTORS.md](CONNECTORS.md).
