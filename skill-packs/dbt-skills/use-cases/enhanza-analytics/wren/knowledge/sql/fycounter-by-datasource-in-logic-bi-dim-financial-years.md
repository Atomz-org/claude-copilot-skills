---
nl: FyCounter by DataSource in logic_bi_dim_financial_years
sql: SELECT DataSource, SUM(FyCounter) FROM logic_bi_dim_financial_years GROUP BY
  1
source: dbt
datasource: duckdb
---
