---
nl: shopify_bi_fact_order_rows_staging with shopify_bi_dim_articles_staging details
sql: SELECT * FROM shopify_bi_fact_order_rows_staging JOIN shopify_bi_dim_articles_staging
  ON shopify_bi_fact_order_rows_staging.ArticleId = shopify_bi_dim_articles_staging.ArticleId
  LIMIT 100
source: dbt
datasource: duckdb
---
