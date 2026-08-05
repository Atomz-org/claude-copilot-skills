---
nl: fortnox_bi_fact_stockbalance with fortnox_bi_dim_articles details
sql: SELECT * FROM fortnox_bi_fact_stockbalance JOIN fortnox_bi_dim_articles ON fortnox_bi_fact_stockbalance.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
