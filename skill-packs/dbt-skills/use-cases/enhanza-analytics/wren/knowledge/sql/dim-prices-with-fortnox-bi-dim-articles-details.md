---
nl: dim_prices with fortnox_bi_dim_articles details
sql: SELECT * FROM dim_prices JOIN fortnox_bi_dim_articles ON dim_prices.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
