---
nl: fact_offers with fortnox_bi_dim_customers details
sql: SELECT * FROM fact_offers JOIN fortnox_bi_dim_customers ON fact_offers.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
