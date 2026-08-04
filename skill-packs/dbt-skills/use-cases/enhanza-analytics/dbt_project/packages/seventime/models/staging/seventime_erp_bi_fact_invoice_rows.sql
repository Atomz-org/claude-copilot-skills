{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with main as (
 select
    cast(i.invoiceNumber as int64) InvoiceNo
    , i.OrgId || '-' || i._id InvoiceId
    , date(i.invoiceDate) InvoiceDate
    , {{ blank_to_null('i.ourReferenceName') }} OurReference
    , i.currencyCode Currency
    , ifnull(i.currencyRate, 1) CurrencyRate
    , cast( null as INT) as AccountNumber
    , {{ blank_to_null('json_extract_scalar(r, "$.articleNumber")') }} ArticleNumber
    , {{ blank_to_null('json_extract_scalar(r, "$.description")') }} Description
    , ifnull(cast(json_extract_scalar(r, '$.numberOfItems') as numeric), 0) DeliveredQuantity
    , {{ blank_to_null('json_extract_scalar(r, "$.unit")') }} Unit
    , cast(null as FLOAT64) as PriceBeforeDiscount
    , cast(null as FLOAT64) as Discount
    , cast(null as STRING) as DiscountType
    , cast(null as FLOAT64) as PriceAfterDiscount
    , ifnull(cast(json_extract_scalar(r, '$.totalAmount') as numeric), 0) * ifnull(i.currencyRate, 1) SalesValue
    , ifnull(cast(json_extract_scalar(r, '$.unitPrice') as numeric), 0) - ifnull(cast(json_extract_scalar(r, '$.unitCost') as numeric), 0) ContributionValue
    , cast(null as STRING) as invoiceType
    , cast(null as DATE) as InvoicePeriodStart
    , cast(null as DATE) as InvoicePeriodEnd
    , cast(null as INT) as ContractReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , i.OrgId
    , i.OrgId || '-' || json_extract_scalar(r, '$.expenseItem') ArticleId
    , i.OrgId || '-' || i.customer CustomerId
    , cast(null as STRING) as AccountId
    , cast(null as STRING) as CostCenterID
    , i.OrgId || '-' || i.project ProjectId
    , cast(null as STRING) as FinancialYearID
  from {{ source('seventime_api', 'invoices') }} i
  , unnest(cast(json_extract_array(i.invoiceItems) as array<json>)) r
)
select
  InvoiceNo
  , InvoiceId
  , InvoiceDate
  , OurReference
  , AccountNumber
  , ArticleNumber
  , DeliveredQuantity
  , Unit
  , PriceBeforeDiscount
  , Discount
  , DiscountType
  , PriceAfterDiscount
  , SalesValue
  , ContributionValue
  , InvoiceType
  , InvoicePeriodStart
  , InvoicePeriodEnd
  , ContractReference
  , YourOrderNumber
  , TermsOfDelivery
  , TermsOfPayment
  , cast(OrgId as string) as OrgId
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'ArticleId', 'CustomerId', 'CostCenterId', 'ProjectId', 'FinancialYearId', 'AccountId']) }}
from main