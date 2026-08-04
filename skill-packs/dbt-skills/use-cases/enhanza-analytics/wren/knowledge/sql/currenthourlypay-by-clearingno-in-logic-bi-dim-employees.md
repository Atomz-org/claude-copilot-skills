---
nl: CurrentHourlyPay by ClearingNo in logic_bi_dim_employees
sql: SELECT ClearingNo, SUM(CurrentHourlyPay) FROM logic_bi_dim_employees GROUP BY
  1
source: dbt
datasource: duckdb
---
