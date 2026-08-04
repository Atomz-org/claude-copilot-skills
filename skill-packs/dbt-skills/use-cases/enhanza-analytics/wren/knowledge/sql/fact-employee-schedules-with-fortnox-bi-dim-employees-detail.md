---
nl: fact_employee_schedules with fortnox_bi_dim_employees details
sql: SELECT * FROM fact_employee_schedules JOIN fortnox_bi_dim_employees ON fact_employee_schedules.EmployeeId
  = fortnox_bi_dim_employees.EmployeeId LIMIT 100
source: dbt
datasource: duckdb
---
