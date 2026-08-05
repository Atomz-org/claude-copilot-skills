---
nl: fortnox_bi_fact_purchase_orders with fortnox_bi_dim_suppliers details
sql: SELECT * FROM fortnox_bi_fact_purchase_orders JOIN fortnox_bi_dim_suppliers ON
  fortnox_bi_fact_purchase_orders.SupplierId = fortnox_bi_dim_suppliers.SupplierId
  LIMIT 100
source: dbt
datasource: duckdb
---
