---
nl: fact_assets with dim_assets_types details
sql: SELECT * FROM fact_assets JOIN dim_assets_types ON fact_assets.AssetTypeId =
  dim_assets_types.AssetTypeId LIMIT 100
source: dbt
datasource: duckdb
---
