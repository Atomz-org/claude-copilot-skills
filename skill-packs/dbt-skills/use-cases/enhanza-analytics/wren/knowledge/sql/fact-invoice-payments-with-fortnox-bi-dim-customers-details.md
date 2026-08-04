---
nl: fact_invoice_payments with fortnox_bi_dim_customers details
sql: SELECT * FROM fact_invoice_payments JOIN fortnox_bi_dim_customers ON fact_invoice_payments.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
