---
nl: DirectCost by Active in article_prices
sql: SELECT Active, SUM(DirectCost) FROM article_prices GROUP BY 1
source: dbt
datasource: duckdb
---
