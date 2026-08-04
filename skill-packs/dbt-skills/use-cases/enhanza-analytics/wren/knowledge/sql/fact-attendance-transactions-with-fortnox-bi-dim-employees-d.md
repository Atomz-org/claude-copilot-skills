---
nl: fact_attendance_transactions with fortnox_bi_dim_employees details
sql: SELECT * FROM fact_attendance_transactions JOIN fortnox_bi_dim_employees ON fact_attendance_transactions.EmployeeId
  = fortnox_bi_dim_employees.EmployeeId LIMIT 100
source: dbt
datasource: duckdb
---
