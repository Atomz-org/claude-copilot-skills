---
nl: fortnox_bi_fact_absence_transactions with fortnox_bi_dim_employees details
sql: SELECT * FROM fortnox_bi_fact_absence_transactions JOIN fortnox_bi_dim_employees
  ON fortnox_bi_fact_absence_transactions.EmployeeId = fortnox_bi_dim_employees.EmployeeId
  LIMIT 100
source: dbt
datasource: duckdb
---
