---
nl: Total line_item_count in fct_orders
sql: SELECT SUM(line_item_count) FROM fct_orders
source: dbt
datasource: duckdb
---
