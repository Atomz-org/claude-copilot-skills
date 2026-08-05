---
nl: fact_invoice_accruals with fortnox_bi_fact_invoices details
sql: SELECT * FROM fact_invoice_accruals JOIN fortnox_bi_fact_invoices ON fact_invoice_accruals.InvoiceId
  = fortnox_bi_fact_invoices.InvoiceId LIMIT 100
source: dbt
datasource: duckdb
---
