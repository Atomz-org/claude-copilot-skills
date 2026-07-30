{{ config(materialized='ephemeral', enabled = var('is_upsales_enabled', false)) }}

with main as (
  select
    id as OrderNo
    , OrgId || '-' || id as OrderId
    , cast(null as STRING) as InvoiceReference
    , cast(null as STRING) as OfferReference
    , date as OrderDate
    , cast(null as date) as OutboundDate
    , json_extract_scalar(stage, '$.name') as OrderType
    , cast(null as date) as DeliveryDate
    , cast(null as STRING) as DeliveryState
    , json_extract_scalar(user, '$.name') as OurReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as YourReference
    , cast(null as BOOLEAN) as Sent
    , if(closeDate is null, false, true) as NotCompleted
    , cast(null as BOOLEAN) as HouseWork
    , currency as Currency
    , currencyRate as CurrencyRate
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , cast(null as FLOAT64) as TotalVAT
    , value * currencyRate as Net
    , cast(null as FLOAT64) as TaxReduction
    , cast(null as FLOAT64) as Gross
    , cast(null as FLOAT64) as RoundOff
    , cast(null as FLOAT64) as TotalToPay
    , safe_divide(contributionMargin, value) * 100 as ContributionPercent
    , contributionMargin * currencyRate as ContributionValue
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , cast(null as STRING) as WayOfDelivery
    , cast(null as STRING) as DeliveryAddress1
    , cast(null as STRING) as DeliveryAddress2
    , cast(null as STRING) as DeliveryCity
    , cast(null as STRING) as DeliveryCountry
    , cast(null as STRING) as DeliveryZipCode
    , cast(null as STRING) as DeliveryName
    , cast(null as STRING) as RecipientEmail
    , cast(null as STRING) as RecipientPhone
    , cast(null as STRING) as Comments
    , cast(null as BOOLEAN) as hasCopyRemarks
    , cast(null as STRING) as ExternalInvoiceReference1
    , cast(null as STRING) as ExternalInvoiceReference2
    , cast(null as STRING) as Country
    , cast(null as BOOLEAN) as isWarehouseReady
    , cast(null as STRING) as Labels
    , cast(OrgId as string) as OrgId
    , OrgId || '-' || json_extract_scalar(client, '$.id') as CustomerId
    , cast(null as STRING) as StockPointId
    , cast(null as STRING) as LabelId
  from {{ source('upsales_api', 'orders') }}
)
select *
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'LabelId','CustomerId', 'StockPointId']) }}
from main