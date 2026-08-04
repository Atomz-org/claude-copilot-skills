---
nl: shopify_bi_fact_order_rows with shopify_bi_dim_articles details
sql: SELECT * FROM shopify_bi_fact_order_rows JOIN shopify_bi_dim_articles ON shopify_bi_fact_order_rows.ArticleId
  = shopify_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
