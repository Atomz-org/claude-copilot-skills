---
nl: AdministrationFee by DataSource in logic_bi_fact_invoices
sql: SELECT DataSource, SUM(AdministrationFee) FROM logic_bi_fact_invoices GROUP BY
  1
source: dbt
datasource: duckdb
---
