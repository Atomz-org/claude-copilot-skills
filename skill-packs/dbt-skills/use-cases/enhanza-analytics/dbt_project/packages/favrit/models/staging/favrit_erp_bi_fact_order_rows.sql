{{ config(materialized='ephemeral', enabled = var('is_favrit_enabled', false)) }}

-- Adapts Favrit to the unified fact_order_rows contract. Column list, order, and count are
-- copied from fortnox_erp_bi_fact_order_rows.sql, because union_queries() emits a
-- *positional* UNION ALL: a column in the wrong slot with a compatible type unions cleanly
-- and silently transposes the data, and an extra column fails only when a second connector
-- is enabled at once. This adapter previously carried three columns no peer has
-- (OrderRowId, CreatedAt, UpdatedAt) and lacked ArticleNumber — exactly that failure.
--
-- The connector-native columns are not lost: they remain on
-- favrit_bi_fact_order_rows_staging, which is still queryable directly. The adapter is the
-- conformance projection, not the archive.
--
-- OrderDate derives from CreatedAt: Favrit is a point-of-sale system, so the order exists
-- at the moment it is created. The previous NULL discarded the only date the source has.
--
-- ArticleNumber is NULL by the same rule upsales applies: Favrit's order line carries a
-- product_id (mapped to ArticleId) and no human-facing article code, and filling the number
-- from the id would invent an attribute the source does not model.

select
  cast(o.OrderId as string) OrderNum
  , cast(o.OrderId as string) OrderId
  , date(o.CreatedAt) OrderDate
  , cast(null as DATE) DeliveryDate
  , cast(null as string) OurReference
  , cast(o.Currency as string) Currency
  , cast(null as string) ArticleNumber
  , cast(null as string) Description
  , cast(o.OrderedQuantity as float64) OrderedQuantity
  , cast(o.DeliveredQuantity as float64) DeliveredQuantity
  , cast(null as boolean) isVATIncluded
  , cast(o.Price as float64) PriceBeforeDiscount
  , cast(o.Discount as float64) Discount
  , trim({{ blank_to_null('o.DiscountType') }}) DiscountType
  , cast(o.Price as float64) PriceAfterDiscount
  , cast(o.OrderedQuantity * o.Price as float64) SalesValue
  , cast(null as float64) OrderedValue
  , cast(null as float64) ContributionValue
  , cast(o.VAT as float64) VAT
  , cast('0' as string) InvoiceReference
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , cast(null as string) OrgId
  , cast(o.ArticleId as string) ArticleId
  , cast(o.CustomerId as string) CustomerId
  , cast(o.AccountId as string) AccountId
  , cast(o.CostCenterId as string) CostCenterId
  , cast(o.ProjectId as string) ProjectId
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'ArticleId', 'CustomerId', 'AccountId', 'ProjectId', 'CostCenterId']) }}
from {{ ref('favrit_bi_fact_order_rows_staging') }} o
