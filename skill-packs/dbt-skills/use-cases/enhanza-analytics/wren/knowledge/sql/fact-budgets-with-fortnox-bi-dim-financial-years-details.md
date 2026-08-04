---
nl: fact_budgets with fortnox_bi_dim_financial_years details
sql: SELECT * FROM fact_budgets JOIN fortnox_bi_dim_financial_years ON fact_budgets.FinancialYearId
  = fortnox_bi_dim_financial_years.FinancialYearId LIMIT 100
source: dbt
datasource: duckdb
---
