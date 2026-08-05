---
nl: stg_demopos__receipts with stg_demopos__customers details
sql: SELECT * FROM stg_demopos__receipts JOIN stg_demopos__customers ON stg_demopos__receipts.customer_id
  = stg_demopos__customers.customer_id LIMIT 100
source: dbt
datasource: duckdb
---
