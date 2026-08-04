---
nl: fortnox_bi_fact_purchase_orders with fortnox_bi_dim_articles details
sql: SELECT * FROM fortnox_bi_fact_purchase_orders JOIN fortnox_bi_dim_articles ON
  fortnox_bi_fact_purchase_orders.ArticleId = fortnox_bi_dim_articles.ArticleId LIMIT
  100
source: dbt
datasource: duckdb
---
