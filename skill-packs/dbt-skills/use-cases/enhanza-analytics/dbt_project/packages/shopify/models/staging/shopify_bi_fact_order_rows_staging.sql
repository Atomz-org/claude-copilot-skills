{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Grain: one row per Shopify order line item.
--
-- Joins back to shopify_api.orders for the order-level context an order row needs
-- (date, currency, customer, VAT-inclusive flag). Fortnox's equivalent staging model does
-- the same — it joins articles and financial_years — so a join at this layer follows the
-- project rather than the general "staging does no joins" guidance.
--
-- Discount handling: Shopify reports `total_discount` as an AMOUNT for the whole line, not
-- a percentage and not per unit. DiscountType is therefore the literal 'Amount', matching
-- the initcap'd values Fortnox emits, and PriceAfterDiscount divides the discount across
-- the line quantity. A percent-type discount never appears from this source.
--
-- [NEEDS INPUT] Column names assume the loader preserves Shopify REST Admin API line-item
-- field names and lands `tax_lines` as a repeated STRUCT. Verify the landed shape — the
-- VAT rate extraction below is the most likely thing to need adjusting.

with order_context as (
  select
    cast(o.id as string) OrderId
    , cast(o.order_number as int64) OrderNum
    , cast(o.customer_id as string) CustomerId
    , date(o.created_at) OrderDate
    , trim({{ blank_to_null('o.currency') }}) Currency
    , cast(o.taxes_included as boolean) isVATIncluded
  from {{ source('shopify_api', 'orders') }} o
  where
    o.cancelled_at is null
    and date(o.created_at) > date_sub(current_date(), interval 5 year)
)

, line_items as (
  select
    cast(l.id as string) OrderRowId
    , cast(l.order_id as string) OrderId
    , cast(l.variant_id as string) ArticleId
    , trim({{ blank_to_null('l.sku') }}) ArticleNumber
    , trim({{ blank_to_null('l.title') }}) Description
    , cast(l.quantity as float64) OrderedQuantity
    , cast(l.quantity as float64) - cast(coalesce(l.fulfillable_quantity, 0) as float64) DeliveredQuantity
    , cast(l.price as float64) Price
    , cast(coalesce(l.total_discount, 0) as float64) Discount
    -- Shopify puts the VAT rate on tax_lines as a fraction (0.25), Enhanza stores percent.
    , cast(coalesce((select max(t.rate) from unnest(l.tax_lines) t), 0) as float64) * 100 VAT
  from {{ source('shopify_api', 'order_lines') }} l
)

select
  li.OrderRowId
  , li.OrderId
  , oc.OrderNum
  , oc.OrderDate
  , oc.Currency
  , oc.isVATIncluded
  , oc.CustomerId
  , li.ArticleId
  , li.ArticleNumber
  , li.Description
  , li.OrderedQuantity
  , li.DeliveredQuantity
  , li.Price
  , li.Discount
  , li.VAT
  -- Net unit price: strip VAT when the order is stored VAT-inclusive, mirroring the
  -- PriceBeforeDiscount calculation in fortnox_bi_fact_order_rows_staging.
  , round(
      li.Price
      * case when oc.isVATIncluded is not true then 1 else 1 / (1 + li.VAT / 100) end
    , 2) PriceBeforeDiscount
  , round(
      (li.Price
        * case when oc.isVATIncluded is not true then 1 else 1 / (1 + li.VAT / 100) end)
      - (li.Discount / nullif(li.OrderedQuantity, 0))
    , 2) PriceAfterDiscount
  , round(
      li.OrderedQuantity
      * (li.Price
        * case when oc.isVATIncluded is not true then 1 else 1 / (1 + li.VAT / 100) end)
      - li.Discount
    , 2) SalesValue
from line_items li
inner join order_context oc
  on oc.OrderId = li.OrderId
