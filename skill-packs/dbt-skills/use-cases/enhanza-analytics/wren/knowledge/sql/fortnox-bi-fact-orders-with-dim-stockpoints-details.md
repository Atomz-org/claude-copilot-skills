---
nl: fortnox_bi_fact_orders with dim_stockpoints details
sql: SELECT * FROM fortnox_bi_fact_orders JOIN dim_stockpoints ON fortnox_bi_fact_orders.StockPointId
  = dim_stockpoints.StockPointId LIMIT 100
source: dbt
datasource: duckdb
---
