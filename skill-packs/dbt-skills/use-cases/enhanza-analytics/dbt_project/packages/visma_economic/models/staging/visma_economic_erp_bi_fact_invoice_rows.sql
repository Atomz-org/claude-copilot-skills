{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with a as (
  select
    OrgId || '-' || productNumber ArticleId
    , json_extract_scalar(unit, '$.name') Unit
  from {{ source('visma_economic_api', 'products') }}
)
, e as (
  select
    OrgId || '-' || employeeNumber EmployeeId
    , name OurReference
  from {{ source('visma_economic_api', 'employees') }}
)
, fy as ( --financial years snapshot
  select
    OrgId
    , OrgId || '-' || year FinancialYearId
    , parse_date('%Y-%m-%d', fromDate) FromDate
    , parse_date('%Y-%m-%d', toDate) ToDate
  from {{ source('visma_economic_api', 'accounting_years') }}
)
, final as (
  select
    bookedInvoiceNumber InvoiceNo
    , i.OrgId || '-' || bookedInvoiceNumber InvoiceId
    , date(date) InvoiceDate
    , e.OurReference
    , currency Currency
    , cast(null as float64) CurrencyRate
    , cast(null as INT) as AccountNumber
    , cast(null as STRING) as ArticleNumber
    , cast(json_extract_scalar(r, '$.quantity') as float64) DeliveredQuantity
    , coalesce(json_extract_scalar(r, '$.unit.name'), a.Unit) Unit
    , cast(json_extract_scalar(r, '$.unitNetPrice') as float64) PriceBeforeDiscount
    , cast(json_extract_scalar(r, '$.discountPercentage') as float64) Discount
    , 'Percent' DiscountType --no other discount types are available
    , cast(json_extract_scalar(r, '$.unitNetPrice') as float64) * (1 - ifnull(cast(json_extract_scalar(r, '$.discountPercentage') as float64),0)/100) PriceAfterDiscount
    , json_extract_scalar(r, '$.description') ArticleDescription
    , cast(json_extract_scalar(r, '$.totalNetAmount') as float64) SalesValue
    , cast(json_extract_scalar(r, '$.unitNetPrice') as float64) ArticlePrice
    , cast(null as FLOAT64) as ContributionValue
    , cast(null as STRING) as InvoiceType
    , cast(null as DATE) as InvoicePeriodStart
    , cast(null as DATE) as InvoicePeriodEnd
    , cast(null as INT) as ContractReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , i.OrgId
    , i.OrgId || '-' || json_extract_scalar(r, '$.product.productNumber') ArticleId
    , i.OrgId || '-' || json_extract_scalar(customer, '$.customerNumber') CustomerId
    , cast(null as STRING) as AccountId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , fy.FinancialYearId
  from
  {{ source('visma_economic_api', 'invoices_booked') }} i
  , unnest(cast(json_extract_array(i.lines) as array<JSON>)) r
  left join a
    on a.ArticleId=i.OrgId || '-' || json_extract_scalar(r, '$.product.productNumber')
  left join  fy
    on date(i.date) between fy.FromDate and fy.ToDate and fy.OrgId=i.OrgId
  left join e
    on e.EmployeeId = i.OrgId || '-' || json_extract_scalar(references, '$.salesPerson.employeeNumber')
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
from final