---
nl: fortnox_bi_fact_orders with fortnox_bi_dim_customers details
sql: SELECT * FROM fortnox_bi_fact_orders JOIN fortnox_bi_dim_customers ON fortnox_bi_fact_orders.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
