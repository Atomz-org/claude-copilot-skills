---
nl: dim_assets_types with fortnox_bi_dim_company details
sql: SELECT * FROM dim_assets_types JOIN fortnox_bi_dim_company ON dim_assets_types.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
