---
nl: line_item_count by customer_id in fct_orders
sql: SELECT customer_id, SUM(line_item_count) FROM fct_orders GROUP BY 1
source: dbt
datasource: duckdb
---
