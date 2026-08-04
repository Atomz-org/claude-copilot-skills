---
nl: AccountNumber by AccountClass in balance_sheet
sql: SELECT AccountClass, SUM(AccountNumber) FROM balance_sheet GROUP BY 1
source: dbt
datasource: duckdb
---
