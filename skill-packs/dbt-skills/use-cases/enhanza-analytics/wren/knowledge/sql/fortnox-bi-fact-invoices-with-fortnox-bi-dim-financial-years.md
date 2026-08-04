---
nl: fortnox_bi_fact_invoices with fortnox_bi_dim_financial_years details
sql: SELECT * FROM fortnox_bi_fact_invoices JOIN fortnox_bi_dim_financial_years ON
  fortnox_bi_fact_invoices.FinancialYearId = fortnox_bi_dim_financial_years.FinancialYearId
  LIMIT 100
source: dbt
datasource: duckdb
---
