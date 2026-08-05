---
nl: fact_production_orders with fortnox_bi_dim_company details
sql: SELECT * FROM fact_production_orders JOIN fortnox_bi_dim_company ON fact_production_orders.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
