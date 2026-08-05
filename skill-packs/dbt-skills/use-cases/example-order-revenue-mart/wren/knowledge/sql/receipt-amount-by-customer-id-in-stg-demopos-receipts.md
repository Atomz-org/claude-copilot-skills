---
nl: receipt_amount by customer_id in stg_demopos__receipts
sql: SELECT customer_id, SUM(receipt_amount) FROM stg_demopos__receipts GROUP BY 1
source: dbt
datasource: duckdb
---
