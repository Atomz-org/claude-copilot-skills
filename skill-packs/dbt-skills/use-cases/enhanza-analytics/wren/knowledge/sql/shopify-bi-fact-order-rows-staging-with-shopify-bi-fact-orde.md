---
nl: shopify_bi_fact_order_rows_staging with shopify_bi_fact_orders_staging details
sql: SELECT * FROM shopify_bi_fact_order_rows_staging JOIN shopify_bi_fact_orders_staging
  ON shopify_bi_fact_order_rows_staging.OrderId = shopify_bi_fact_orders_staging.OrderId
  LIMIT 100
source: dbt
datasource: duckdb
---
