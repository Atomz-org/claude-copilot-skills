---
nl: fortnox_bi_fact_stocktakings with dim_stockpoints details
sql: SELECT * FROM fortnox_bi_fact_stocktakings JOIN dim_stockpoints ON fortnox_bi_fact_stocktakings.StockPointId
  = dim_stockpoints.StockPointId LIMIT 100
source: dbt
datasource: duckdb
---
