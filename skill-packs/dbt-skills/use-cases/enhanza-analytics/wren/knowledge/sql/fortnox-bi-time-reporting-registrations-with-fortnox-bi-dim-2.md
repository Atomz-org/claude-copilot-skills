---
nl: fortnox_bi_time_reporting_registrations with fortnox_bi_dim_company details
sql: SELECT * FROM fortnox_bi_time_reporting_registrations JOIN fortnox_bi_dim_company
  ON fortnox_bi_time_reporting_registrations.OrgId = fortnox_bi_dim_company.OrgId
  LIMIT 100
source: dbt
datasource: duckdb
---
