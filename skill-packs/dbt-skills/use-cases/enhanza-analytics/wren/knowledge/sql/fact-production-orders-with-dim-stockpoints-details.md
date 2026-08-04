---
nl: fact_production_orders with dim_stockpoints details
sql: SELECT * FROM fact_production_orders JOIN dim_stockpoints ON fact_production_orders.StockPointId
  = dim_stockpoints.stockPointId LIMIT 100
source: dbt
datasource: duckdb
---
