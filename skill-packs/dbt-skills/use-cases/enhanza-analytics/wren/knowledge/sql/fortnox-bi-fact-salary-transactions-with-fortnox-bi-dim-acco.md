---
nl: fortnox_bi_fact_salary_transactions with fortnox_bi_dim_accounts details
sql: SELECT * FROM fortnox_bi_fact_salary_transactions JOIN fortnox_bi_dim_accounts
  ON fortnox_bi_fact_salary_transactions.AccountId = fortnox_bi_dim_accounts.AccountId
  LIMIT 100
source: dbt
datasource: duckdb
---
