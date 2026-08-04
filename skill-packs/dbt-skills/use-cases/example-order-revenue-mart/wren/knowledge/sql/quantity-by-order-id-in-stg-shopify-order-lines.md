---
nl: quantity by order_id in stg_shopify__order_lines
sql: SELECT order_id, SUM(quantity) FROM stg_shopify__order_lines GROUP BY 1
source: dbt
datasource: duckdb
---
