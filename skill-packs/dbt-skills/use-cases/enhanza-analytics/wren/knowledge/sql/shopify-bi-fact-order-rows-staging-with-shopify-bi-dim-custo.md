---
nl: shopify_bi_fact_order_rows_staging with shopify_bi_dim_customers_staging details
sql: SELECT * FROM shopify_bi_fact_order_rows_staging JOIN shopify_bi_dim_customers_staging
  ON shopify_bi_fact_order_rows_staging.CustomerId = shopify_bi_dim_customers_staging.CustomerId
  LIMIT 100
source: dbt
datasource: duckdb
---
