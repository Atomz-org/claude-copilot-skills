{{ config(materialized='ephemeral', enabled = var('is_upsales_enabled', false)) }}

with main as (
  select
    id OrderNum
    , OrgId || '-' || id as OrderId
    , date OrderDate
    , cast(null as DATE) as DeliveryDate
    , json_extract_scalar(user, '$.name') OurReference
    , currency Currency
    , cast(null as STRING) as ArticleNumber
    , cast(null as STRING) as Description
    , cast(json_extract_scalar(r, '$.quantity') as float64) OrderedQuantity
    , cast(null as FLOAT64) as DeliveredQuantity
    , cast(null as BOOLEAN) as isVATIncluded
    , cast(null as FLOAT64) as PriceBeforeDiscount
    , cast(null as FLOAT64) as Discount
    , cast(null as STRING) as DiscountType
    , cast(null as FLOAT64) as PriceAfterDiscount
    , cast(json_extract_scalar(r, '$.price') as float64) * cast(json_extract_scalar(r, '$.quantity') as float64) SalesValue
    , cast(null as FLOAT64) as OrderedValue
    , cast(json_extract_scalar(r, '$.purchaseCost') as float64) * cast(json_extract_scalar(r, '$.quantity') as float64) ContributionValue
    , cast(null as FLOAT64) as VAT
    , '0' InvoiceReference
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , cast(OrgId as string) as OrgId
    , OrgId || '-' || json_extract_scalar(r, '$.product.id') ArticleId
    , OrgId || '-' || json_extract_scalar(client, '$.id') CustomerId
    , cast(null as STRING) as AccountId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
  from {{ source('upsales_api', 'orders') }}
    , unnest(json_extract_array(orderRow)) r
)
select *
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'ArticleId','CustomerId', 'AccountId', 'ProjectId', 'CostCenterId']) }}
from main