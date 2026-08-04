---
nl: fortnox_bi_time_reporting_registrations with fortnox_bi_dim_articles details
sql: SELECT * FROM fortnox_bi_time_reporting_registrations JOIN fortnox_bi_dim_articles
  ON fortnox_bi_time_reporting_registrations.ArticleId = fortnox_bi_dim_articles.ArticleId
  LIMIT 100
source: dbt
datasource: duckdb
---
