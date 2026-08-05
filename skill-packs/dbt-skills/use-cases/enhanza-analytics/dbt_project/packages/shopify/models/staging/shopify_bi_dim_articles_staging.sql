{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Grain: one row per Shopify product variant.
--
-- Variant grain, not product grain, and deliberately so: an order line references a
-- variant, so a product-grain dimension could not join to fact_order_rows without fanning
-- out. Product-level attributes (title, vendor, product_type) repeat across a product's
-- variants, which is the normal cost of a conformed article dimension.
--
-- [NEEDS INPUT] Assumes the loader lands one row per variant — either a flattened
-- `variants` array or a separate variant feed. If shopify_api.products is product-grain
-- with a repeated `variants` field, this needs an `unnest`; confirm the landed shape
-- before the first build.
-- [NEEDS INPUT] Shopify exposes no cost price on the REST product resource unless Shopify
-- cost tracking is on, so PurchasePrice is left NULL in the adapter rather than guessed.

select
  cast(p.variant_id as string) ArticleId
  , trim({{ blank_to_null('p.variant_sku') }}) ArticleNumber
  , trim({{ blank_to_null('p.title') }}) ArticleName
  , trim({{ blank_to_null('p.variant_title') }}) VariantName
  , cast(p.product_id as string) ProductId
  , trim({{ blank_to_null('p.vendor') }}) Manufacturer
  , trim({{ blank_to_null('p.product_type') }}) Type
  , cast(p.variant_price as float64) SalesPrice
  , cast(p.variant_inventory_quantity as int64) QuantityInStock
  , cast(p.variant_requires_shipping as boolean) StockGoods
  , cast(p.status = 'active' as boolean) Active
  , trim({{ blank_to_null('p.variant_barcode') }}) EAN
  , cast(p.variant_grams as float64) Weight
  , trim({{ blank_to_null('p.tags') }}) Tags
  , cast(p.created_at as timestamp) CreatedAt
  , cast(p.updated_at as timestamp) UpdatedAt
from {{ source('shopify_api', 'products') }} p
