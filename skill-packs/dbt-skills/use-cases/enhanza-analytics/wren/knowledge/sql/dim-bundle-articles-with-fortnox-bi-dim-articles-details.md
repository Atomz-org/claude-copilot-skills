---
nl: dim_bundle_articles with fortnox_bi_dim_articles details
sql: SELECT * FROM dim_bundle_articles JOIN fortnox_bi_dim_articles ON dim_bundle_articles.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
