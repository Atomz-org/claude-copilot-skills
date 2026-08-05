---
nl: Show shopify_bi_fact_orders_staging where FinancialStatus is pending
sql: SELECT * FROM shopify_bi_fact_orders_staging WHERE FinancialStatus = 'pending'
  LIMIT 100
source: dbt
datasource: duckdb
---
