---
nl: Show stg_demopos__receipts where receipt_status is paid
sql: SELECT * FROM stg_demopos__receipts WHERE receipt_status = 'paid' LIMIT 100
source: dbt
datasource: duckdb
---
