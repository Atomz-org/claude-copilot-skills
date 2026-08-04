---
nl: fact_employee_schedules with fortnox_bi_dim_company details
sql: SELECT * FROM fact_employee_schedules JOIN fortnox_bi_dim_company ON fact_employee_schedules.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
