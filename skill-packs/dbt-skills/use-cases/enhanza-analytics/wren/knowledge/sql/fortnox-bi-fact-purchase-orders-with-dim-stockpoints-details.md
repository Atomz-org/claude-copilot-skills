---
nl: fortnox_bi_fact_purchase_orders with dim_stockpoints details
sql: SELECT * FROM fortnox_bi_fact_purchase_orders JOIN dim_stockpoints ON fortnox_bi_fact_purchase_orders.stockPointId
  = dim_stockpoints.stockPointId LIMIT 100
source: dbt
datasource: duckdb
---
