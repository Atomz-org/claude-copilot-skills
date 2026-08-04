---
nl: fact_stockbalance with fortnox_bi_dim_company details
sql: SELECT * FROM fact_stockbalance JOIN fortnox_bi_dim_company ON fact_stockbalance.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
