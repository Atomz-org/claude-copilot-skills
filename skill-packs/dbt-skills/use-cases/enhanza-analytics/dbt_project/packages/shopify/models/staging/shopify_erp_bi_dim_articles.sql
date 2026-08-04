{{ config(materialized='ephemeral', enabled = var('is_shopify_enabled', false)) }}

-- Adapts Shopify to the common unified schema so erp_bi_dim_articles can union it.
-- Column list, order, and count are copied from fortnox_erp_bi_dim_articles.sql — 10
-- columns before add_erp_fields(). union_queries() emits a positional UNION ALL.
--
-- Grain note: ArticleId is the Shopify *variant* id, not the product id, because an order
-- line references a variant. Joining fact_order_rows to a product-grain dimension would
-- fan out.
--
-- Shopify's `vendor` maps to Manufacturer rather than SupplierName. It is one field and
-- Fortnox has both; filling both from one source would invent a supplier relationship that
-- Shopify does not model.
--
-- [NEEDS INPUT] PurchasePrice is NULL: Shopify exposes unit cost only when cost tracking is
-- enabled, and it is not on the REST product resource. If the tenant has it, map it here.

select
  a.ArticleId
  , a.ArticleNumber
  , cast(a.ArticleName as STRING) as ArticleName
  , a.Manufacturer
  , cast(null as float64) PurchasePrice
  , a.StockGoods
  , cast(a.QuantityInStock as float64) QuantityInStock
  , cast(null as string) SupplierName
  , cast(null as string) SupplierNumber
  , a.Active
  , {{ add_erp_fields(columns=['ArticleId']) }}
from {{ ref('shopify_bi_dim_articles_staging') }} a
