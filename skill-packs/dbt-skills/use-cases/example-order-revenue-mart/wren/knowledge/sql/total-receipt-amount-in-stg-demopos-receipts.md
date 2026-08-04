---
nl: Total receipt_amount in stg_demopos__receipts
sql: SELECT SUM(receipt_amount) FROM stg_demopos__receipts
source: dbt
datasource: duckdb
---
