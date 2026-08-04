---
nl: fact_absence_transactions with fortnox_bi_dim_company details
sql: SELECT * FROM fact_absence_transactions JOIN fortnox_bi_dim_company ON fact_absence_transactions.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
