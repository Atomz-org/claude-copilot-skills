---
nl: fortnox_bi_fact_invoice_rows with fortnox_bi_dim_customers details
sql: SELECT * FROM fortnox_bi_fact_invoice_rows JOIN fortnox_bi_dim_customers ON fortnox_bi_fact_invoice_rows.CustomerId
  = fortnox_bi_dim_customers.CustomerId LIMIT 100
source: dbt
datasource: duckdb
---
