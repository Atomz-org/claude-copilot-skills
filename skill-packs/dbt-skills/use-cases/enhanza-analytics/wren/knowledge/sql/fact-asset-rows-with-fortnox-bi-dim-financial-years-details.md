---
nl: fact_asset_rows with fortnox_bi_dim_financial_years details
sql: SELECT * FROM fact_asset_rows JOIN fortnox_bi_dim_financial_years ON fact_asset_rows.FinancialYearId
  = fortnox_bi_dim_financial_years.FinancialYearId LIMIT 100
source: dbt
datasource: duckdb
---
