{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with main as (
  select
    quoteNumber OfferNo
    , OrgId || '-' || quoteNumber OfferId
    , date(quoteDate) OfferDate
    , date(deliveryDate) DeliveryDate
    , date(validToDate) ExpireDate
    , initcap({{ blank_to_null('ourReferenceName') }}) OurReference
    , cast(null as STRING) as YourReference
    , if(sentDate is null, FALSE, TRUE) Sent
    , cast(null as BOOLEAN) as NotCompleted
    , cast(null as STRING) as OrderReference
    , invoiceNumber InvoiceReference
    , cast(null as BOOLEAN) as HouseWork
    , currencyCode Currency
    , ifnull(currencyRate, 1) CurrencyRate
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , totalTaxAmount * ifnull(currencyRate, 1) TotalVAT
    , totalAmount * ifnull(currencyRate, 1) Net
    , cast(null as FLOAT64) as TaxReduction
    , cast(null as FLOAT64) as Gross
    , cast(null as FLOAT64) as RoundOff
    , totalAmountInclTax * ifnull(currencyRate, 1) TotalToPay
    , cast(null as FLOAT64) as ContributionPercent
    , totalCost ContributionValue
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
    , cast(null as BOOLEAN) as CopyRemarks
    , cast(null as STRING) as Country
    , cast(null as STRING) as Labels
    , cast(OrgId as string) as OrgId
    , OrgId || '-' || {{ blank_to_null('customerNumber') }} CustomerId
    , cast(null as STRING) as ProjectId
    , cast(null as STRING) as CostCenterId
from
  {{ source('seventime_api', 'quotes') }}
where
  date(quoteDate) > DATE_SUB(current_date(), interval 5 year)
)
select *
  , {{ add_erp_fields(columns=['OfferId', 'OrgId', 'CustomerId', 'ProjectId', 'CostCenterId']) }}
from main