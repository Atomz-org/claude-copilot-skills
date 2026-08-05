---
nl: fortnox_bi_fact_stockbalance with dim_stockpoints details
sql: SELECT * FROM fortnox_bi_fact_stockbalance JOIN dim_stockpoints ON fortnox_bi_fact_stockbalance.stockPointId
  = dim_stockpoints.stockPointId LIMIT 100
source: dbt
datasource: duckdb
---
