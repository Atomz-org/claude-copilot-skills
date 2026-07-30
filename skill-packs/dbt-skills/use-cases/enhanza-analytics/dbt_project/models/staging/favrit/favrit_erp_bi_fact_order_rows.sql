{{ config(materialized='ephemeral', enabled = var('is_favrit_enabled', false)) }}

select
  cast(o.OrderId as string) OrderId
  , cast(o.OrderRowId as string) OrderRowId
  , cast(null as DATE) OrderDate
  , cast(null as DATE) DeliveryDate
  , cast(o.OrderId as string) OrderNum
  , cast(null as string) OurReference
  , cast(o.Currency as string) Currency
  , cast(o.ArticleId as string) ArticleId
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
  , cast(o.CustomerId as string) CustomerId
  , cast(o.AccountId as string) AccountId
  , cast(o.CostCenterId as string) CostCenterId
  , cast(o.ProjectId as string) ProjectId
  , cast(o.CreatedAt as timestamp) CreatedAt
  , cast(o.UpdatedAt as timestamp) UpdatedAt
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'ArticleId', 'CustomerId', 'AccountId', 'ProjectId', 'CostCenterId']) }}
from {{ ref('favrit_bi_fact_order_rows_staging') }} o
