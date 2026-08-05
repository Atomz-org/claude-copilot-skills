---
nl: ContributionValue by AccountId in fact_sales
sql: SELECT AccountId, SUM(ContributionValue) FROM fact_sales GROUP BY 1
source: dbt
datasource: duckdb
---
