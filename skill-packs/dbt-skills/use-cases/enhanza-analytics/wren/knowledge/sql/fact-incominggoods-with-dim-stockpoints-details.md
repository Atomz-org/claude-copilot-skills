---
nl: fact_incominggoods with dim_stockpoints details
sql: SELECT * FROM fact_incominggoods JOIN dim_stockpoints ON fact_incominggoods.stockPointId
  = dim_stockpoints.StockPointId LIMIT 100
source: dbt
datasource: duckdb
---
