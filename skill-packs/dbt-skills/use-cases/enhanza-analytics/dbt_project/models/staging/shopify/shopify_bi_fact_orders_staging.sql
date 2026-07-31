{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Grain: one row per Shopify order.
--
-- Cancelled orders are excluded, matching how fortnox_bi_fact_orders_staging drops
-- `cancelled is not true`. Shopify soft-cancels by stamping `cancelled_at`, so the filter
-- is a null check rather than a boolean.
--
-- CurrencyRate is 1.0 rather than NULL and that is deliberate: Fortnox stores amounts in
-- the document currency and multiplies by CurrencyRate to reach the base currency, whereas
-- Shopify's `total_price` and friends are already in the shop's own currency. A rate of 1
-- makes the two sources' amount columns mean the same thing after the union. Orders placed
-- in a presentment currency keep that code in Currency; the amounts stay shop-currency.
--
-- [NEEDS INPUT] Column names assume the loader preserves Shopify REST Admin API field
-- names, with `shipping_address` landed as a STRUCT. Verify against the landed schema.
-- [NEEDS INPUT] The 5-year window mirrors Fortnox's `OrderDate > date_sub(..., 5 year)`.
-- Confirm Enhanza wants the same horizon for Shopify.

select
  cast(o.order_number as int64) OrderNo
  , cast(o.id as string) OrderId
  , cast(o.customer_id as string) CustomerId
  , date(o.created_at) OrderDate
  , date(o.processed_at) ProcessedDate
  , date(o.closed_at) ClosedDate
  , trim({{ blank_to_null('o.name') }}) OrderName
  , trim({{ blank_to_null('o.financial_status') }}) FinancialStatus
  , trim({{ blank_to_null('o.fulfillment_status') }}) FulfillmentStatus
  , trim({{ blank_to_null('o.currency') }}) Currency
  , cast(o.total_price as float64) TotalToPay
  , cast(o.subtotal_price as float64) Net
  , cast(o.total_tax as float64) TotalVAT
  , cast(o.total_discounts as float64) TotalDiscounts
  , cast(o.total_line_items_price as float64) TotalLineItemsPrice
  , cast(o.taxes_included as boolean) isVATIncluded
  , trim({{ blank_to_null('o.shipping_address.address1') }}) DeliveryAddress1
  , trim({{ blank_to_null('o.shipping_address.address2') }}) DeliveryAddress2
  , initcap({{ blank_to_null('o.shipping_address.city') }}) DeliveryCity
  , initcap({{ blank_to_null('o.shipping_address.country') }}) DeliveryCountry
  , REGEXP_REPLACE({{ blank_to_null('o.shipping_address.zip') }}, ' ', '') DeliveryZipCode
  , trim({{ blank_to_null('o.shipping_address.name') }}) DeliveryName
  , trim({{ blank_to_null('o.email') }}) RecipientEmail
  , trim({{ blank_to_null('o.phone') }}) RecipientPhone
  , trim({{ blank_to_null('o.note') }}) Comments
  , trim({{ blank_to_null('o.tags') }}) Labels
  , trim({{ blank_to_null('o.source_name') }}) SourceName
  , cast(o.created_at as timestamp) CreatedAt
  , cast(o.updated_at as timestamp) UpdatedAt
from {{ source('shopify_api', 'orders') }} o
where
  o.cancelled_at is null
  and date(o.created_at) > date_sub(current_date(), interval 5 year)
