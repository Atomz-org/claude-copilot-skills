---
nl: shopify_bi_fact_orders with shopify_bi_dim_customers details
sql: SELECT * FROM shopify_bi_fact_orders JOIN shopify_bi_dim_customers ON shopify_bi_fact_orders.CustomerId
  = shopify_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
