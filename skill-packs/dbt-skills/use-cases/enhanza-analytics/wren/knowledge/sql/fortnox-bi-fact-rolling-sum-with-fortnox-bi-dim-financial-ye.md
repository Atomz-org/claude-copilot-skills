---
nl: fortnox_bi_fact_rolling_sum with fortnox_bi_dim_financial_years details
sql: SELECT * FROM fortnox_bi_fact_rolling_sum JOIN fortnox_bi_dim_financial_years
  ON fortnox_bi_fact_rolling_sum.FinancialYearId = fortnox_bi_dim_financial_years.FinancialYearId
  LIMIT 100
source: dbt
datasource: duckdb
---
