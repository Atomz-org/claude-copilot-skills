---
nl: fact_assets with fortnox_bi_dim_company details
sql: SELECT * FROM fact_assets JOIN fortnox_bi_dim_company ON fact_assets.OrgId =
  fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
