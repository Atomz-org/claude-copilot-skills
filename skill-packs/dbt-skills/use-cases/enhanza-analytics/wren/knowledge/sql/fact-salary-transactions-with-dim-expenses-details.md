---
nl: fact_salary_transactions with dim_expenses details
sql: SELECT * FROM fact_salary_transactions JOIN dim_expenses ON fact_salary_transactions.ExpenseId
  = dim_expenses.ExpenseId LIMIT 100
source: dbt
datasource: duckdb
---
