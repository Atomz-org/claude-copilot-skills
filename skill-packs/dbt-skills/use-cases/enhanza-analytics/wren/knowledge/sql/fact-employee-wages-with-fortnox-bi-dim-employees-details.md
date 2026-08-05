---
nl: fact_employee_wages with fortnox_bi_dim_employees details
sql: SELECT * FROM fact_employee_wages JOIN fortnox_bi_dim_employees ON fact_employee_wages.EmployeeId
  = fortnox_bi_dim_employees.EmployeeId LIMIT 100
source: dbt
datasource: duckdb
---
