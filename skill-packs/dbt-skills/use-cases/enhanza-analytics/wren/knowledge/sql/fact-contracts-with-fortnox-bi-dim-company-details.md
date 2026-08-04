---
nl: fact_contracts with fortnox_bi_dim_company details
sql: SELECT * FROM fact_contracts JOIN fortnox_bi_dim_company ON fact_contracts.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
