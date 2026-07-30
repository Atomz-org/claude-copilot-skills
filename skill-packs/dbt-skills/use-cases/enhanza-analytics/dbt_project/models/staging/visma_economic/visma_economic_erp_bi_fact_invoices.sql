{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}


with s as ( --sent invoices
  select distinct
    OrgId || '-' || json_extract_scalar(invoice, '$.bookedInvoiceNumber') InvoiceId
    , true Sent
  from {{ source('visma_economic_api', 'invoices_sent') }}
)
, fy as ( --financial years snapshot
  select
    OrgId
    , OrgId || '-' || year FinancialYearId
    , parse_date('%Y-%m-%d', fromDate) FromDate
    , parse_date('%Y-%m-%d', toDate) ToDate
  from {{ source('visma_economic_api', 'accounting_years') }}
)
, e as (
  select
    OrgId || '-' || employeeNumber EmployeeId
    , name OurReference
  from {{ source('visma_economic_api', 'employees') }}
)
, final as (
  select
    bookedInvoiceNumber InvoiceNo
    , i.OrgId || '-' || bookedInvoiceNumber InvoiceId
    , date(date) InvoiceDate
    , cast(null as DATE) as OutboundDate
    , cast(null as DATE) as DeliveryDate
    , date(dueDate) DueDate
    , if (dueDate < current_date() and remainder <> 0, true, false) IsDue
    , case
      when s.Sent is null then "NotSent"
      when s.sent is true then case
        when remainder = 0 then "Paid"
        when remainder <> 0 then case
          when abs(date_diff(current_date(), dueDate, day)) between 0 and 15 then "0-15d"
          when abs(date_diff(current_date(), dueDate, day)) between 16 and 30 then "16-30d"
          when abs(date_diff(current_date(), dueDate, day)) between 31 and 45 then "31-45d"
          when abs(date_diff(current_date(), DueDate, day)) between 46 and 60 then "46-60d"
          when abs(date_diff(current_date(), dueDate, day)) between 61 and 90 then "61-90d"
          when abs(date_diff(current_date(), dueDate, day)) between 91 and 120 then "91-120d"
          when abs(date_diff(current_date(), dueDate, day)) > 120 then ">120d"
          when dueDate is null then 'NO_DUE_DATE'
          else 'WHAT?'
        end
        else 'WOW??'
      end
      else "[calc_error]"
    end DueStatus
    , cast(null as DATE) as FinalPayDate
    , cast(null as INT) as Reminders
    , cast(null as DATE) as LastRemindDate
    , cast(null as STRING) as isCredit
    , e.OurReference
    , cast(null as STRING) as YourReference
    , cast(null as STRING) as YourOrderNumber
    , coalesce(s.Sent, false) Sent
    , currency Currency
    , cast(null as float64) CurrencyRate --requires additional info!
    --for below rows, change 1 to currency rate when available
    , grossAmountInBaseCurrency * 1 Gross
    , netAmountInBaseCurrency * 1 Net
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , vatAmount * 1 TotalVAT
    , (grossAmountInBaseCurrency - remainderInBaseCurrency) * 1 TotalToPay
    , remainderInBaseCurrency * 1 Balance
    , roundingAmount * 1 RoundOff
    , grossAmountInBaseCurrency * 1 Total
    , cast(null as BOOLEAN) as HouseWork
    , cast(null as FLOAT64) as ContributionValue
    , json_extract_scalar(notes, '$.heading') Comments
    , cast(null as STRING) as Remarks
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
    , cast(i.OrgId as string) as OrgId
    , i.OrgId || '-' || json_extract_scalar(customer, '$.customerNumber') CustomerId
    , fy.FinancialYearId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , cast(null as STRING) as PriceList
  from
    {{ source('visma_economic_api', 'invoices_booked') }} i
  left join s
    on s.InvoiceId=i.OrgId || '-' || i.bookedInvoiceNumber
  left join fy
    on i.date between fy.FromDate and fy.ToDate
    and i.OrgId=fy.OrgId
  left join e
    on e.EmployeeId = i.OrgId || '-' || json_extract_scalar(references, '$.salesPerson.employeeNumber')
)
select *
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'CustomerId', 'FinancialYearId', 'CostCenterId', 'ProjectId']) }}
from final