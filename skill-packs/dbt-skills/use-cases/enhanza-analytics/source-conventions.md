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

## Example source naming

- `source('fortnox', 'invoices')`
- `source('tripletex', 'accounts')`
- `source('erp', 'sales_transactions')`

These names are examples and should be adapted to the actual upstream systems in the target project.
