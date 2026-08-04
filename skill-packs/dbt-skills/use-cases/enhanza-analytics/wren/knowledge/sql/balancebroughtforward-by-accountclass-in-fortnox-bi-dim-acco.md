---
nl: BalanceBroughtForward by AccountClass in fortnox_bi_dim_accounts
sql: SELECT AccountClass, SUM(BalanceBroughtForward) FROM fortnox_bi_dim_accounts
  GROUP BY 1
source: dbt
datasource: duckdb
---
