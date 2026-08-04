---
nl: fact_locked_period with fortnox_bi_dim_company details
sql: SELECT * FROM fact_locked_period JOIN fortnox_bi_dim_company ON fact_locked_period.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
