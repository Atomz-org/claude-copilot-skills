---
nl: fact_invoice_payments with fortnox_bi_dim_company details
sql: SELECT * FROM fact_invoice_payments JOIN fortnox_bi_dim_company ON fact_invoice_payments.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
