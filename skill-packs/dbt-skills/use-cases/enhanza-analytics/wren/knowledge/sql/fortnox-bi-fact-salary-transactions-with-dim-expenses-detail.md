---
nl: fortnox_bi_fact_salary_transactions with dim_expenses details
sql: SELECT * FROM fortnox_bi_fact_salary_transactions JOIN dim_expenses ON fortnox_bi_fact_salary_transactions.ExpenseId
  = dim_expenses.ExpenseId LIMIT 100
source: dbt
datasource: duckdb
---
