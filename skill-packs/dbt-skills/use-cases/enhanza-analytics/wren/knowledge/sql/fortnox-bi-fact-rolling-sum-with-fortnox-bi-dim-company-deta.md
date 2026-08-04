---
nl: fortnox_bi_fact_rolling_sum with fortnox_bi_dim_company details
sql: SELECT * FROM fortnox_bi_fact_rolling_sum JOIN fortnox_bi_dim_company ON fortnox_bi_fact_rolling_sum.OrgId
  = fortnox_bi_dim_company.OrgId LIMIT 100
source: dbt
datasource: duckdb
---
