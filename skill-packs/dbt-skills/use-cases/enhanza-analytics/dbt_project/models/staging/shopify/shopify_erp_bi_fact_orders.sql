{{ config(materialized='ephemeral', enabled = var('is_shopify_enabled', false)) }}

-- Adapts Shopify to the common unified schema so erp_bi_fact_orders can union it.
-- Column list, order, and count are copied from fortnox_erp_bi_fact_orders.sql — 49
-- columns before add_erp_fields(). union_queries() emits a positional UNION ALL.
--
-- Amount semantics: Fortnox stores document-currency amounts and multiplies by CurrencyRate
-- to reach base currency; Shopify's amounts are already shop-currency, so CurrencyRate is
-- 1.0 and the amount columns are directly comparable after the union.
--   Net   <- subtotal_price  (excl. tax, after line discounts)
--   Gross <- total_price     (incl. tax and shipping)
--   TotalToPay <- total_price
--
-- [NEEDS INPUT] Freight is NULL. Shopify carries shipping on `total_shipping_price_set`,
-- a nested money-set whose landed shape depends on the loader; map it once that is known
-- rather than guessing a JSON path.
-- [NEEDS INPUT] type-verify against Fortnox before the first union build — these are
-- passed through raw in fortnox_bi_fact_orders_staging so their type is not readable from
-- the SQL: InvoiceReference, OfferReference, DeliveryDate, Sent, NotCompleted, HouseWork,
-- TaxReduction, hasCopyRemarks, isWarehouseReady, ExternalInvoiceReference1/2.

select
  o.OrderNo
  , o.OrderId
  , cast(null as string) InvoiceReference
  , cast(null as string) OfferReference
  , o.OrderDate
  , o.ProcessedDate OutboundDate
  , cast(null as string) OrderType
  , cast(null as date) DeliveryDate
  , trim(initcap(o.FulfillmentStatus)) DeliveryState
  , cast(null as string) OurReference
  , o.OrderName YourOrderNumber
  , cast(null as string) YourReference
  , cast(null as boolean) Sent
  , cast(null as boolean) NotCompleted
  , cast(null as boolean) HouseWork
  , o.Currency
  , cast(1 as float64) CurrencyRate
  , cast(null as float64) Freight
  , cast(null as float64) AdministrationFee
  , o.TotalVAT
  , o.Net
  , cast(null as float64) TaxReduction
  , o.TotalToPay Gross
  , cast(null as float64) RoundOff
  , o.TotalToPay
  , cast(null as float64) ContributionPercent
  , cast(null as float64) ContributionValue
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , cast(null as string) WayOfDelivery
  , o.DeliveryAddress1
  , o.DeliveryAddress2
  , o.DeliveryCity
  , o.DeliveryCountry
  , o.DeliveryZipCode
  , o.DeliveryName
  , o.RecipientEmail
  , o.RecipientPhone
  , o.Comments
  , cast(null as boolean) hasCopyRemarks
  , cast(null as string) ExternalInvoiceReference1
  , cast(null as string) ExternalInvoiceReference2
  , o.DeliveryCountry Country
  , cast(null as boolean) isWarehouseReady
  , o.Labels
  , cast(null as string) OrgId
  , o.CustomerId
  , cast(null as string) StockPointId
  , cast(null as string) LabelId
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'LabelId', 'CustomerId', 'StockPointId']) }}
from {{ ref('shopify_bi_fact_orders_staging') }} o
