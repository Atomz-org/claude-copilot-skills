---
nl: order_amount by customer_id in stg_shopify__orders
sql: SELECT customer_id, SUM(order_amount) FROM stg_shopify__orders GROUP BY 1
source: dbt
datasource: duckdb
---
