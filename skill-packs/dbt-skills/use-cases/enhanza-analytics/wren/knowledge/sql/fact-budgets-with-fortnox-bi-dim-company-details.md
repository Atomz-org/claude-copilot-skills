---
nl: fact_budgets with fortnox_bi_dim_company details
sql: SELECT * FROM fact_budgets JOIN fortnox_bi_dim_company ON fact_budgets.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
