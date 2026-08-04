---
nl: fact_stockbalance with dim_stockpoints details
sql: SELECT * FROM fact_stockbalance JOIN dim_stockpoints ON fact_stockbalance.stockPointId
  = dim_stockpoints.stockPointId LIMIT 100
source: dbt
datasource: duckdb
---
