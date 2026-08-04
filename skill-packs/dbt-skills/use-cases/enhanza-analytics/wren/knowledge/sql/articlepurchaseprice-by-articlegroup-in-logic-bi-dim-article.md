---
nl: ArticlePurchasePrice by ArticleGroup in logic_bi_dim_articles
sql: SELECT ArticleGroup, SUM(ArticlePurchasePrice) FROM logic_bi_dim_articles GROUP
  BY 1
source: dbt
datasource: duckdb
---
