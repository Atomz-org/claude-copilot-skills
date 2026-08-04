---
nl: fact_offer_rows with fortnox_bi_dim_company details
sql: SELECT * FROM fact_offer_rows JOIN fortnox_bi_dim_company ON fact_offer_rows.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
