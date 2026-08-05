---
nl: fortnox_bi_fact_offers with fortnox_bi_dim_customers details
sql: SELECT * FROM fortnox_bi_fact_offers JOIN fortnox_bi_dim_customers ON fortnox_bi_fact_offers.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
