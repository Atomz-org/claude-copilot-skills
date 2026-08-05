---
nl: fact_offer_rows with fortnox_bi_dim_accounts details
sql: SELECT * FROM fact_offer_rows JOIN fortnox_bi_dim_accounts ON fact_offer_rows.AccountId
  = fortnox_bi_dim_accounts.AccountId LIMIT 100
source: dbt
datasource: duckdb
---
