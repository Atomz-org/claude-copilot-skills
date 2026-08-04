---
nl: Total order_amount in stg_shopify__orders
sql: SELECT SUM(order_amount) FROM stg_shopify__orders
source: dbt
datasource: duckdb
---
