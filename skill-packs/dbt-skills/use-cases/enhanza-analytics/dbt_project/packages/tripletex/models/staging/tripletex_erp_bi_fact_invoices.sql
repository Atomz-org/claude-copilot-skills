{{ config(materialized='ephemeral', enabled = var('is_tripletex_enabled', false)) }}

with main as (


select
  cast(invoiceNumber as int64) InvoiceNo
  , cast(i.OrgId as string) || '-' || cast(invoiceNumber as string) InvoiceId
  , date(invoiceDate) InvoiceDate
  , cast(null as DATE) as OutboundDate
  , date(deliveryDate) DeliveryDate
  , date(invoiceDueDate) DueDate
  , if(date(invoiceDueDate) < current_date() and amountOutstanding > 0, TRUE, FALSE) IsDue
  , case
    when ehfSendStatus IS NULL or ehfSendStatus = '' then "NotSent"
    when ehfSendStatus IS NOT NULL then case
      when amountOutstanding = 0 then "Paid"
      when amountOutstanding > 0 then case
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 0
        and 15 then "0-15d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 16
        and 30 then "16-30d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 31
        and 45 then "31-45d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 46
        and 60 then "46-60d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 61
        and 90 then "61-90d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 91
        and 120 then "91-120d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) > 120 then ">120d"
        when invoiceDueDate is null then 'NO_DUE_DATE'
        else 'WHAT?'
      end
      else 'WOW??'
    end
    else "[calc_error]"
  end DueStatus
  , cast(null as DATE) as FinalPayDate
  , array_length(json_extract_array(reminders)) Reminders
  , cast(null as DATE) as LastRemindDate
  , cast(isCreditNote as STRING) as isCredit
  , cast(null as STRING) as OurReference
  , cast(null as STRING) as YourReference
  , cast(null as STRING) as YourOrderNumber
  , if(ehfSendStatus IS NOT NULL AND ehfSendStatus <> '', TRUE, FALSE) Sent
  , json_extract_scalar(currency, '$.code') Currency
  , cast(1 as FLOAT64) CurrencyRate
  , cast(null as FLOAT64) as Gross
  , amountExcludingVat Net
  , cast(null as FLOAT64) as Freight
  , cast(null as FLOAT64) as AdministrationFee
  , amount - amountExcludingVat TotalVAT
  , amount TotalToPay
  , amountOutstanding Balance
  , amountRoundoff RoundOff
  , amount Total
  , cast(null as BOOLEAN) as HouseWork
  , cast(null as FLOAT64) as ContributionValue
  , {{ blank_to_null('invoiceComment') }} Comments
  , {{ blank_to_null('comment') }} Remarks
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
  , cast(creditedInvoice as string) CreditInvoiceReference
  , {{ blank_to_null('kid') }} InvoiceOCR
  , cast(null as STRING) as OfferReference
  , cast(null as STRING) as OrderReference
  , cast(null as STRING) as ContractReference
  , cast(null as BOOLEAN) as isWarehouseReady
  , cast(null as STRING) as Labels
  , cast(i.OrgId as string) as OrgId
  , i.OrgId || '-' || json_extract_scalar(customer, '$.id') CustomerId
  , cast(null as STRING) as FinancialYearId
  , cast(null as STRING) as CostCenterId
  , cast(null as STRING) as ProjectId
  , cast(null as STRING) as PriceList
from {{ source('tripletex_api', 'invoice') }} i
where invoiceNumber is not null
  and isCredited is not true
)
select *
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'CustomerId', 'FinancialYearId', 'CostCenterId', 'ProjectId']) }}
from main

