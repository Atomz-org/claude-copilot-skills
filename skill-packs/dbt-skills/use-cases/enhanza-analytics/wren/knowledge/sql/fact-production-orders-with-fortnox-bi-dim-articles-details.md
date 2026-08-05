---
nl: fact_production_orders with fortnox_bi_dim_articles details
sql: SELECT * FROM fact_production_orders JOIN fortnox_bi_dim_articles ON fact_production_orders.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
