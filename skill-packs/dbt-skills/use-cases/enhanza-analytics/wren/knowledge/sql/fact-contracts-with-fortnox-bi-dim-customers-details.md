---
nl: fact_contracts with fortnox_bi_dim_customers details
sql: SELECT * FROM fact_contracts JOIN fortnox_bi_dim_customers ON fact_contracts.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
