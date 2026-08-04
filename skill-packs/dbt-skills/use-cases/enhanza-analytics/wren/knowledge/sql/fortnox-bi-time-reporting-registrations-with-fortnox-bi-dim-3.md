---
nl: fortnox_bi_time_reporting_registrations with fortnox_bi_dim_customers details
sql: SELECT * FROM fortnox_bi_time_reporting_registrations JOIN fortnox_bi_dim_customers
  ON fortnox_bi_time_reporting_registrations.CustomerId = fortnox_bi_dim_customers.CustomerId
  LIMIT 100
source: dbt
datasource: duckdb
---
