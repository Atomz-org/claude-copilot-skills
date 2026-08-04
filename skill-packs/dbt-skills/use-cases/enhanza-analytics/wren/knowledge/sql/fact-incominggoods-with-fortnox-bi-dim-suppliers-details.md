---
nl: fact_incominggoods with fortnox_bi_dim_suppliers details
sql: SELECT * FROM fact_incominggoods JOIN fortnox_bi_dim_suppliers ON fact_incominggoods.SupplierId
  = fortnox_bi_dim_suppliers.SupplierId LIMIT 100
source: dbt
datasource: duckdb
---
