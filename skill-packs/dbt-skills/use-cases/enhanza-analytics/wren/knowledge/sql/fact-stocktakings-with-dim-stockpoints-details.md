---
nl: fact_stocktakings with dim_stockpoints details
sql: SELECT * FROM fact_stocktakings JOIN dim_stockpoints ON fact_stocktakings.StockPointId
  = dim_stockpoints.StockPointId LIMIT 100
source: dbt
datasource: duckdb
---
