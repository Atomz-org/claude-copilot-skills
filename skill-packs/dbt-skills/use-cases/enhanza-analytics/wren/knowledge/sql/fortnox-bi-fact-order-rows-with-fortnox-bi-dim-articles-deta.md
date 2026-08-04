---
nl: fortnox_bi_fact_order_rows with fortnox_bi_dim_articles details
sql: SELECT * FROM fortnox_bi_fact_order_rows JOIN fortnox_bi_dim_articles ON fortnox_bi_fact_order_rows.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
