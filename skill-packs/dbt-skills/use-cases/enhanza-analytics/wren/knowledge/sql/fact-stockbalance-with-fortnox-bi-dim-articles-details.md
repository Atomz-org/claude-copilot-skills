---
nl: fact_stockbalance with fortnox_bi_dim_articles details
sql: SELECT * FROM fact_stockbalance JOIN fortnox_bi_dim_articles ON fact_stockbalance.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
