---
nl: ChargeHours by ArticleId in fact_time_reporting
sql: SELECT ArticleId, SUM(ChargeHours) FROM fact_time_reporting GROUP BY 1
source: dbt
datasource: duckdb
---
