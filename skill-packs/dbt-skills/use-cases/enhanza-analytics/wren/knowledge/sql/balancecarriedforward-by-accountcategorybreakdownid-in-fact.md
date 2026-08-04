---
nl: BalanceCarriedForward by AccountCategoryBreakdownID in fact_balance
sql: SELECT AccountCategoryBreakdownID, SUM(BalanceCarriedForward) FROM fact_balance
  GROUP BY 1
source: dbt
datasource: duckdb
---
