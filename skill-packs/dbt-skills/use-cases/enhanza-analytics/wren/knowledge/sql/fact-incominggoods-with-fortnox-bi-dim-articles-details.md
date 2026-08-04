---
nl: fact_incominggoods with fortnox_bi_dim_articles details
sql: SELECT * FROM fact_incominggoods JOIN fortnox_bi_dim_articles ON fact_incominggoods.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
