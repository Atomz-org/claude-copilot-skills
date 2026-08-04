---
nl: fct_orders with dim_customers details
sql: SELECT * FROM fct_orders JOIN dim_customers ON fct_orders.customer_id = dim_customers.customer_id
  LIMIT 100
source: dbt
datasource: duckdb
---
