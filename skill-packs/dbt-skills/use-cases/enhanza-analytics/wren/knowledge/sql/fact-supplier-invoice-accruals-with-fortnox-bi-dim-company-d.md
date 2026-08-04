---
nl: fact_supplier_invoice_accruals with fortnox_bi_dim_company details
sql: SELECT * FROM fact_supplier_invoice_accruals JOIN fortnox_bi_dim_company ON fact_supplier_invoice_accruals.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
