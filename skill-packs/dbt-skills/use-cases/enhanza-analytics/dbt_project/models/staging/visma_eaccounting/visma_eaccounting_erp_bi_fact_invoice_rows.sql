{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with fy as ( --fiscalyears source snapshot
  SELECT
    OrgId || '-' || Id FinancialYearId
    , StartDate FromDate
    , EndDate ToDate
  FROM
    {{ source('visma_eaccounting_api', 'fiscalyears') }}
),
final as (
  select
    InvoiceNumber InvoiceNo
    , i.OrgId || '-' || i.Id InvoiceId
    , date(i.InvoiceDate) InvoiceDate
    , i.OurReference
    , i.CurrencyCode Currency
    , ifnull(i.CurrencyRate, 1) CurrencyRate
    , cast(null as INT) as AccountNumber
    , json_extract_scalar(r, '$.ArticleNumber') ArticleNumber
    , json_extract_scalar(r, '$.Text') Description
    , ifnull(cast(json_extract_scalar(r, '$.Quantity') as numeric), 0) DeliveredQuantity
    , json_extract_scalar(r, '$.UnitAbbreviationEnglish') Unit
    , cast(null as FLOAT64) as PriceBeforeDiscount
    , cast(null as FLOAT64) as Discount
    , cast(null as STRING) as DiscountType
    , cast(null as FLOAT64) as PriceAfterDiscount
    , ifnull(cast(json_extract_scalar(r, '$.AmountNoVat') as numeric), 0) * ifnull(i.CurrencyRate, 1) SalesValue
    , ifnull(cast(JSON_EXTRACT_SCALAR(JSON_EXTRACT(r, '$.ContributionMargin'), '$.Amount') as numeric), 0) ContributionValue
    , 'INVOICE' InvoiceType
    , cast(null as DATE) as InvoicePeriodStart
    , cast(null as DATE) as InvoicePeriodEnd
    , cast(null as INT) as ContractReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , i.OrgId
    , i.OrgId || '-' || json_extract_scalar(r, '$.ArticleId') ArticleId
    , i.OrgId || '-' || i.CustomerId CustomerId
    , cast(null as STRING) as AccountId
    , i.OrgId || '-' || json_extract_scalar(r, '$.CostCenterItemId1') CostCenterId
    , i.OrgId || '-' || json_extract_scalar(r, '$.ProjectId') ProjectId
    , fy.FinancialYearId
  FROM
    {{ source('visma_eaccounting_api', 'customerinvoices') }} i
    , UNNEST(CAST(JSON_EXTRACT_ARRAY(i.Rows) AS ARRAY<JSON>)) r
    left join fy on i.InvoiceDate between fy.FromDate and fy.ToDate
  where length(json_extract_scalar(r, '$.ArticleNumber')) > 0
  or ifnull(cast(json_extract_scalar(r, '$.AmountNoVat') as numeric), 0) <> 0
  or ifnull(cast(JSON_EXTRACT_SCALAR(JSON_EXTRACT(r, '$.ContributionMargin'), '$.Amount') as numeric), 0) <> 0
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