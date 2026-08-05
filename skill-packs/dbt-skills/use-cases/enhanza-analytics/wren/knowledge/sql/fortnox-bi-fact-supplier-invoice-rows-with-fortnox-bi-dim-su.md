---
nl: fortnox_bi_fact_supplier_invoice_rows with fortnox_bi_dim_suppliers details
sql: SELECT * FROM fortnox_bi_fact_supplier_invoice_rows JOIN fortnox_bi_dim_suppliers
  ON fortnox_bi_fact_supplier_invoice_rows.SupplierId = fortnox_bi_dim_suppliers.SupplierId
  LIMIT 100
source: dbt
datasource: duckdb
---
