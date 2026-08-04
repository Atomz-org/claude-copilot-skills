---
nl: dim_supplier_items with fortnox_bi_dim_suppliers details
sql: SELECT * FROM dim_supplier_items JOIN fortnox_bi_dim_suppliers ON dim_supplier_items.SupplierId
  = fortnox_bi_dim_suppliers.SupplierId LIMIT 100
source: dbt
datasource: duckdb
---
