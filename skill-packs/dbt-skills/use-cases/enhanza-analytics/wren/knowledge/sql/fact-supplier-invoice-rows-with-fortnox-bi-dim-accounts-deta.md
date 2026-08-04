---
nl: fact_supplier_invoice_rows with fortnox_bi_dim_accounts details
sql: SELECT * FROM fact_supplier_invoice_rows JOIN fortnox_bi_dim_accounts ON fact_supplier_invoice_rows.AccountId
  = fortnox_bi_dim_accounts.AccountId LIMIT 100
source: dbt
datasource: duckdb
---
