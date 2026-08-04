---
nl: fact_attendance_transactions with fortnox_bi_dim_company details
sql: SELECT * FROM fact_attendance_transactions JOIN fortnox_bi_dim_company ON fact_attendance_transactions.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
