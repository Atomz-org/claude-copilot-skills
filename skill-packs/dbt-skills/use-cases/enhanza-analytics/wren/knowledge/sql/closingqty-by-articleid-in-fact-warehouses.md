---
nl: ClosingQty by ArticleId in fact_warehouses
sql: SELECT ArticleId, SUM(ClosingQty) FROM fact_warehouses GROUP BY 1
source: dbt
datasource: duckdb
---
