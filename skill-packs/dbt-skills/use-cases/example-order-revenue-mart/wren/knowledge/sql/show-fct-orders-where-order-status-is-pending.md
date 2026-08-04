---
nl: Show fct_orders where order_status is pending
sql: SELECT * FROM fct_orders WHERE order_status = 'pending' LIMIT 100
source: dbt
datasource: duckdb
---
