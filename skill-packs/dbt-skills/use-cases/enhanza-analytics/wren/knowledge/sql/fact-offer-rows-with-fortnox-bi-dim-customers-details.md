---
nl: fact_offer_rows with fortnox_bi_dim_customers details
sql: SELECT * FROM fact_offer_rows JOIN fortnox_bi_dim_customers ON fact_offer_rows.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
