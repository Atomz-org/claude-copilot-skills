{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with main as (

select
  cast(invoiceNumber as int64) InvoiceNo
  , OrgId || '-' || _id InvoiceId
  , date(invoiceDate) InvoiceDate
  , cast(null as DATE) as OutboundDate
  , cast(null as DATE) as DeliveryDate
  , date(dueDate) DueDate	
  , if(date(dueDate)<current_date(), TRUE, FALSE) IsDue
  , CASE
    when sentDate IS null then "NotSent"
    else CASE
      when paymentDate is not null then "Paid"
      else CASE
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) between 0
        and 15 then "0-15d"
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) between 16
        and 30 then "16-30d"
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) between 31
        and 45 then "31-45d"
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) between 46
        and 60 then "46-60d"
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) between 61
        and 90 then "61-90d"
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) between 91
        and 120 then "91-120d"
        when ABS(DATE_DIFF(current_date(), date(dueDate), day)) > 120 then ">120d"
        when DueDate is null then 'NO_DUE_DATE'
        else 'WHAT?'
      end
    end
  end DueStatus
  , date(paymentDate) FinalPayDate
  , if(reminderDate is null, 0, 1) Reminders
  , date(reminderDate) LastRemindDate
  , cast(null as STRING) as isCredit
  , {{ blank_to_null('ourReferenceName') }} OurReference
  , cast(null as STRING) as YourReference
  , trim({{ blank_to_null('yourOrderNumber') }}) YourOrderNumber
  , if(sentDate is null, FALSE, TRUE) Sent
  , currencyCode Currency
  , ifnull(currencyRate, 1) CurrencyRate
  , cast(null as FLOAT64) as Gross
  , totalAmount * ifnull(currencyRate, 1) Net
  , cast(null as FLOAT64) as Freight
  , cast(null as FLOAT64) as AdministrationFee
  , totalTaxAmount * ifnull(currencyRate, 1) TotalVAT	
  , totalAmountInclTax * ifnull(currencyRate, 1) TotalToPay
  , cast(null as FLOAT64) as Balance
  , totalAmountRounding * ifnull(currencyRate, 1) RoundOff
  , totalAmountInclTax * ifnull(currencyRate, 1) Total
  , cast(null as BOOLEAN) as HouseWork
  , totalCost ContributionValue
  , {{ blank_to_null('notes') }} Comments
  , {{ blank_to_null('description') }} Remarks
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
  , cast(null as STRING) as Country
  , cast(null as STRING) as ExternalInvoiceReference1
  , cast(null as STRING) as ExternalInvoiceReference2
  , cast(null as STRING) as CreditInvoiceReference
  , cast(null as STRING) as InvoiceOCR
  , cast(null as STRING) as OfferReference
  , cast(null as STRING) as OrderReference
  , cast(null as STRING) as ContractReference
  , cast(null as BOOLEAN) as isWarehouseReady
  , cast(null as STRING) as Labels
  , cast(OrgId as string) as OrgId
  , OrgId || '-' || customer CustomerId
  , cast(null as STRING) as FinancialYearId
  , cast(null as STRING) as CostCenterId
  , cast(null as STRING) as ProjectId
  , cast(null as STRING) as PriceList
from {{ source('seventime_api', 'invoices') }} i
)
select *
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'CustomerId', 'FinancialYearId', 'CostCenterId', 'ProjectId']) }}
from main