---
nl: fact_budgets with fortnox_bi_dim_accounts details
sql: SELECT * FROM fact_budgets JOIN fortnox_bi_dim_accounts ON fact_budgets.AccountId
  = fortnox_bi_dim_accounts.AccountId LIMIT 100
source: dbt
datasource: duckdb
---
