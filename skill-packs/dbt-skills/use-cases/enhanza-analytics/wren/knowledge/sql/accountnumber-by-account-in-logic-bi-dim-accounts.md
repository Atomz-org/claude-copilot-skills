---
nl: AccountNumber by Account in logic_bi_dim_accounts
sql: SELECT Account, SUM(AccountNumber) FROM logic_bi_dim_accounts GROUP BY 1
source: dbt
datasource: duckdb
---
