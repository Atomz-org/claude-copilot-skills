---
nl: fortnox_bi_fact_invoice_rows with fortnox_bi_fact_invoices details
sql: SELECT * FROM fortnox_bi_fact_invoice_rows JOIN fortnox_bi_fact_invoices ON fortnox_bi_fact_invoice_rows.InvoiceId
  = fortnox_bi_fact_invoices.InvoiceId LIMIT 100
source: dbt
datasource: duckdb
---
