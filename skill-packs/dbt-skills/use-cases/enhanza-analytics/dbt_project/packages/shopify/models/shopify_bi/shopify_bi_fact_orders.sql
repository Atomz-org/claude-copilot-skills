{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Source-aligned Shopify order fact, one row per order, cancelled orders excluded.
-- See shopify_bi_dim_customers.sql for why this uses an explicit config rather than
-- {{ auto_config() }}.

select
  OrderId
  , OrderNo
  , OrderName
  , CustomerId
  , OrderDate
  , ProcessedDate
  , ClosedDate
  , FinancialStatus
  , FulfillmentStatus
  , Currency
  , Net
  , TotalVAT
  , TotalToPay
  , TotalDiscounts
  , TotalLineItemsPrice
  , isVATIncluded
  , DeliveryName
  , DeliveryAddress1
  , DeliveryAddress2
  , DeliveryZipCode
  , DeliveryCity
  , DeliveryCountry
  , RecipientEmail
  , RecipientPhone
  , Comments
  , Labels
  , SourceName
  , CreatedAt
  , UpdatedAt
from {{ ref('shopify_bi_fact_orders_staging') }}
