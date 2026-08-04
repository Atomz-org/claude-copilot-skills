---
nl: fact_stocktakings with fortnox_bi_dim_articles details
sql: SELECT * FROM fact_stocktakings JOIN fortnox_bi_dim_articles ON fact_stocktakings.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
