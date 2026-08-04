---
nl: fact_stocktakings with fortnox_bi_dim_company details
sql: SELECT * FROM fact_stocktakings JOIN fortnox_bi_dim_company ON fact_stocktakings.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
