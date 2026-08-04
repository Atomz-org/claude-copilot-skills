---
nl: stg_shopify__order_lines with stg_shopify__orders details
sql: SELECT * FROM stg_shopify__order_lines JOIN stg_shopify__orders ON stg_shopify__order_lines.order_id
  = stg_shopify__orders.order_id LIMIT 100
source: dbt
datasource: duckdb
---
