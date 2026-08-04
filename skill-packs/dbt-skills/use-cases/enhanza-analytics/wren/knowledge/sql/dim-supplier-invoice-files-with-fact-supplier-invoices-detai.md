---
nl: dim_supplier_invoice_files with fact_supplier_invoices details
sql: SELECT * FROM dim_supplier_invoice_files JOIN fact_supplier_invoices ON dim_supplier_invoice_files.SupplierInvoiceId
  = fact_supplier_invoices.SupplierInvoiceId LIMIT 100
source: dbt
datasource: duckdb
---
