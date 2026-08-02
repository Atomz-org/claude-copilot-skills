{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  ArticleId
  , ArticleNumber
  , cast(Description as STRING) as ArticleName
  , Manufacturer
  , PurchasePrice
  , StockGoods
  , QuantityInStock
  , SupplierName
  , SupplierNumber
  , Active
  , {{ add_erp_fields(columns=['ArticleId']) }}
from {{ ref('fortnox_bi_dim_articles_staging') }}