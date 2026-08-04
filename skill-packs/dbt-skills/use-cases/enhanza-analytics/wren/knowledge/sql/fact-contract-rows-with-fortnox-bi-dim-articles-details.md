---
nl: fact_contract_rows with fortnox_bi_dim_articles details
sql: SELECT * FROM fact_contract_rows JOIN fortnox_bi_dim_articles ON fact_contract_rows.ArticleId
  = fortnox_bi_dim_articles.ArticleId LIMIT 100
source: dbt
datasource: duckdb
---
