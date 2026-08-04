---
nl: AmountPerUnit by CauseCode in fact_salaries
sql: SELECT CauseCode, SUM(AmountPerUnit) FROM fact_salaries GROUP BY 1
source: dbt
datasource: duckdb
---
