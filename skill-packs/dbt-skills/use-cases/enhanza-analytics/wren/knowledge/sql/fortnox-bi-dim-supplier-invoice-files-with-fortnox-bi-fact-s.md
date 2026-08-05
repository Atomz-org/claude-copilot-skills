---
nl: fortnox_bi_dim_supplier_invoice_files with fortnox_bi_fact_supplier_invoices details
sql: SELECT * FROM fortnox_bi_dim_supplier_invoice_files JOIN fortnox_bi_fact_supplier_invoices
  ON fortnox_bi_dim_supplier_invoice_files.SupplierInvoiceId = fortnox_bi_fact_supplier_invoices.SupplierInvoiceId
  LIMIT 100
source: dbt
datasource: duckdb
---
