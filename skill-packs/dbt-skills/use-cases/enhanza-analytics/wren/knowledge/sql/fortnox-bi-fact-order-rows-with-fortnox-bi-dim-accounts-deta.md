---
nl: fortnox_bi_fact_order_rows with fortnox_bi_dim_accounts details
sql: SELECT * FROM fortnox_bi_fact_order_rows JOIN fortnox_bi_dim_accounts ON fortnox_bi_fact_order_rows.AccountId
  = fortnox_bi_dim_accounts.AccountId LIMIT 100
source: dbt
datasource: duckdb
---
