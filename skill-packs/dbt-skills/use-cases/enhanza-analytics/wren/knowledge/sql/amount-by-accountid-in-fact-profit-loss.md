---
nl: Amount by AccountId in fact_profit_loss
sql: SELECT AccountId, SUM(Amount) FROM fact_profit_loss GROUP BY 1
source: dbt
datasource: duckdb
---
