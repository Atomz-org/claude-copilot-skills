{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Source-aligned Shopify article dimension, at product-variant grain.
-- See shopify_bi_dim_customers.sql for why this uses an explicit config rather than
-- {{ auto_config() }}.

select
  ArticleId
  , ArticleNumber
  , ArticleName
  , VariantName
  , ProductId
  , Manufacturer
  , Type
  , SalesPrice
  , QuantityInStock
  , StockGoods
  , Active
  , EAN
  , Weight
  , Tags
  , CreatedAt
  , UpdatedAt
from {{ ref('shopify_bi_dim_articles_staging') }}
