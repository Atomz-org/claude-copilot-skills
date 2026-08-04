---
nl: shopify_bi_fact_order_rows with shopify_bi_fact_orders details
sql: SELECT * FROM shopify_bi_fact_order_rows JOIN shopify_bi_fact_orders ON shopify_bi_fact_order_rows.OrderId
  = shopify_bi_fact_orders.OrderId LIMIT 100
source: dbt
datasource: duckdb
---
