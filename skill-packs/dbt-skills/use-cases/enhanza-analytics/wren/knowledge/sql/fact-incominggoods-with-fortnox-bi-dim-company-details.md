---
nl: fact_incominggoods with fortnox_bi_dim_company details
sql: SELECT * FROM fact_incominggoods JOIN fortnox_bi_dim_company ON fact_incominggoods.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
