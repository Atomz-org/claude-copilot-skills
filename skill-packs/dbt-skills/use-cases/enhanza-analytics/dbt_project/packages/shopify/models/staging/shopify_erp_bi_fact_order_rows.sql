{{ config(materialized='ephemeral', enabled = var('is_shopify_enabled', false)) }}

-- Adapts Shopify to the common unified schema so erp_bi_fact_order_rows can union it.
-- Column list, order, and count are copied from fortnox_erp_bi_fact_order_rows.sql — 28
-- columns before add_erp_fields(). union_queries() emits a positional UNION ALL.
--
-- NOTE: favrit_erp_bi_fact_order_rows.sql does NOT match this shape — it emits 30 columns
-- in a different order (it adds OrderRowId, CreatedAt, UpdatedAt and omits ArticleNumber).
-- Fortnox is followed here because it is the reference the skill and CONNECTORS.md name,
-- and because it is the connector this one will be built alongside. The Favrit/Fortnox
-- divergence is pre-existing and is reported separately — it is not introduced here, and a
-- Favrit+Fortnox tenant would already fail on this union.
--
-- OrderRowId is deliberately dropped: the Fortnox contract has no row-id column, so the
-- unified fact is order-row grain without a surrogate key. The id stays available on
-- shopify_bi_fact_order_rows for source-aligned consumers.
--
-- OrderedValue equals SalesValue for Shopify. Fortnox distinguishes ordered from delivered
-- value because its rows carry both quantities against a reservation model; Shopify has no
-- equivalent, so both are computed from OrderedQuantity.
--
-- DiscountType is the literal 'Amount': Shopify reports `total_discount` as a line-level
-- amount, never a percentage. The value is initcap'd to match Fortnox's `initcap(...)`.

select
  r.OrderNum
  , r.OrderId
  , r.OrderDate
  , cast(null as date) DeliveryDate
  , cast(null as string) OurReference
  , r.Currency
  , r.ArticleNumber
  , r.Description
  , r.OrderedQuantity
  , r.DeliveredQuantity
  , r.isVATIncluded
  , r.PriceBeforeDiscount
  , r.Discount
  , cast('Amount' as string) DiscountType
  , r.PriceAfterDiscount
  , r.SalesValue
  , r.SalesValue OrderedValue
  , cast(null as float64) ContributionValue
  , r.VAT
  , cast(null as string) InvoiceReference
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , cast(null as string) OrgId
  , r.ArticleId
  , r.CustomerId
  , cast(null as string) AccountId
  , cast(null as string) CostCenterId
  , cast(null as string) ProjectId
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'ArticleId', 'CustomerId', 'AccountId', 'ProjectId', 'CostCenterId']) }}
from {{ ref('shopify_bi_fact_order_rows_staging') }} r
