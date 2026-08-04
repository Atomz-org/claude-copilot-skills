---
nl: dim_supplier_items with fortnox_bi_dim_articles details
sql: SELECT * FROM dim_supplier_items JOIN fortnox_bi_dim_articles ON dim_supplier_items.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
