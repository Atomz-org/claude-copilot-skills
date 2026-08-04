---
nl: fact_offers with fortnox_bi_dim_company details
sql: SELECT * FROM fact_offers JOIN fortnox_bi_dim_company ON fact_offers.OrgId =
  fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
