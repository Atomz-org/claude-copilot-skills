---
nl: fact_incominggoods with fortnox_bi_fact_purchase_orders details
sql: SELECT * FROM fact_incominggoods JOIN fortnox_bi_fact_purchase_orders ON fact_incominggoods.purchaseOrderId
  = fortnox_bi_fact_purchase_orders.purchaseOrderId LIMIT 100
source: dbt
datasource: duckdb
---
