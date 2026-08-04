---
nl: fortnox_bi_fact_invoices with fortnox_bi_dim_company details
sql: SELECT * FROM fortnox_bi_fact_invoices JOIN fortnox_bi_dim_company ON fortnox_bi_fact_invoices.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
