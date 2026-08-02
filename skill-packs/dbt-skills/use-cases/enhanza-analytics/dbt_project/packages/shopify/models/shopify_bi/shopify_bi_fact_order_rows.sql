{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Source-aligned Shopify order-line fact, one row per line item on a non-cancelled order.
-- Keeps OrderRowId, which the unified erp_bi_fact_order_rows contract has no column for.
-- See shopify_bi_dim_customers.sql for why this uses an explicit config rather than
-- {{ auto_config() }}.

select
  OrderRowId
  , OrderId
  , OrderNum
  , OrderDate
  , CustomerId
  , ArticleId
  , ArticleNumber
  , Description
  , Currency
  , OrderedQuantity
  , DeliveredQuantity
  , isVATIncluded
  , Price
  , PriceBeforeDiscount
  , PriceAfterDiscount
  , Discount
  , VAT
  , SalesValue
from {{ ref('shopify_bi_fact_order_rows_staging') }}
