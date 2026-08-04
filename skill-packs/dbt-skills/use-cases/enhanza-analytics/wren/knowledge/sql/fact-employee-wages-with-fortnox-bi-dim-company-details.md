---
nl: fact_employee_wages with fortnox_bi_dim_company details
sql: SELECT * FROM fact_employee_wages JOIN fortnox_bi_dim_company ON fact_employee_wages.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
