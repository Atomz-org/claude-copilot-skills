---
nl: Show dim_customers where region is EMEA
sql: SELECT * FROM dim_customers WHERE region = 'EMEA' LIMIT 100
source: dbt
datasource: duckdb
---
