---
nl: fact_supplier_invoices with fortnox_bi_dim_suppliers details
sql: SELECT * FROM fact_supplier_invoices JOIN fortnox_bi_dim_suppliers ON fact_supplier_invoices.SupplierId
  = fortnox_bi_dim_suppliers.SupplierId LIMIT 100
source: dbt
datasource: duckdb
---
