# Cube metric guidance for Enhanza

Cube is the semantic layer for the Enhanza app experience, so this use case package treats it as the place where business metrics become governed and reusable.

## Metric design principles

- Define the business metric once in the dbt logic layer and expose it through Cube.
- Keep metrics symmetric and safe for aggregation, especially financial measures.
- Use Cube to enforce access control and tenant isolation rather than embedding that logic in ad hoc SQL.

## Good metric candidates

- Revenue
- Gross margin
- Outstanding invoices
- Accounts receivable totals
- Order and transaction counts

## Recommended implementation pattern

1. Ensure the dbt logic model carries the grain and dimensions needed for the metric.
2. Define the metric in Cube over the logic model, not directly over raw source tables.
3. Validate the metric against the dbt logic layer before exposing it to the app.

## Guidance for this use case

- Use the logic layer as the canonical business definition.
- Make the metric name reflect the business meaning, not the technical implementation.
- Favor shared metrics over one-off metric definitions in the app layer.
