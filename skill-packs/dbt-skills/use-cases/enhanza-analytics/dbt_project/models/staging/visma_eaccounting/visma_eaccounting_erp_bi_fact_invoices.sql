{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

--fact_invoices
--check variables in Fortnox - how are they calculated?


with fy as ( --fiscalyears source snapshot
  select
    OrgId || '-' || Id FinancialYearId
    , StartDate FromDate
    , EndDate ToDate
  from
    {{ source('visma_eaccounting_api', 'fiscalyears') }}
)
, iRows0 as (
  select
    i.OrgId || '-' || i.Id InvoiceId
    , ifnull(cast(JSON_EXTRACT_SCALAR(JSON_EXTRACT(r, '$.ContributionMargin'), '$.Amount') as numeric), 0) ContributionValue
    , ifnull(cast(JSON_EXTRACT_SCALAR(r, '$.DiscountFixedAmount') as numeric), 0) DiscountValue
  from {{ source('visma_eaccounting_api', 'customerinvoices') }} i
  , UNNEST(CAST(JSON_EXTRACT_ARRAY(i.Rows) AS ARRAY<JSON>)) r
)
, iRows as (
  select 
    InvoiceId
    , sum(ContributionValue) ContributionValue
    , sum(DiscountValue) DiscountValue
  from iRows0
  group by InvoiceId
)
, final as (
  select
    InvoiceNumber InvoiceNo
    , i.OrgId || '-' || i.Id InvoiceId
    , date(i.InvoiceDate) InvoiceDate
    , cast(null as DATE) as OutboundDate
    , cast(null as DATE) as DeliveryDate
    , date(i.DueDate) DueDate
    , IF (i.DueDate < current_date() and i.RemainingAmount <> 0, TRUE, FALSE) IsDue
    , CASE
      when i.IsNotDelivered IS TRUE then "Sending by email has failed"
      when i.IsNotDelivered IS FALSE then CASE
        when i.PaymentStatus =0 then "Paid"
        when i.PaymentStatus <> 0 then CASE
          when ABS(DATE_DIFF(current_date(), i.DueDate, day)) between 0
          and 15 then "0-15d"
          when ABS(DATE_DIFF(current_date(), i.DueDate, day)) between 16
          and 30 then "16-30d"
          when ABS(DATE_DIFF(current_date(), i.DueDate, day)) between 31
          and 45 then "31-45d"
          when ABS(DATE_DIFF(current_date(), i.DueDate, day)) between 46
          and 60 then "46-60d"
          when ABS(DATE_DIFF(current_date(), i.DueDate, day)) between 61
          and 90 then "61-90d"
          when ABS(DATE_DIFF(current_date(), DueDate, day)) between 91
          and 120 then "91-120d"
          when ABS(DATE_DIFF(current_date(), i.DueDate, day)) > 120 then ">120d"
          when i.DueDate is null then 'NO_DUE_DATE'
          else 'WHAT?'
        end
        else 'WOW??'
      end
      else "[calc_error]"
    end DueStatus
    , if(i.RemainingAmount=0, date(i.PaymentDate), null) FinalPayDate
    , case
      when i.PaymentReminderIssued is false then 0 --no reminders
      when i.FactoringInvoiceStatus=6 then 1 --6 - FirstReminderSent, this field is null in test data
      when i.FactoringInvoiceStatus=11 then 2 --11 - SecondReminderSent
      else 1 --just in case
    end Reminders
    , cast(null as DATE) as LastRemindDate
    , cast(null as STRING) as isCredit
    , i.OurReference
    , i.YourReference
    , cast(null as STRING) as YourOrderNumber
    , not i.IsNotDelivered Sent
    , i.CurrencyCode Currency
    , ifnull(i.CurrencyRate, 1) CurrencyRate
    , (i.TotalAmount + iRows.DiscountValue) * ifnull(i.CurrencyRate, 1) Gross
    , (i.TotalAmount - i.TotalVatAmount) * ifnull(i.CurrencyRate, 1) Net
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , i.TotalVatAmount * ifnull(i.CurrencyRate, 1) TotalVAT
    , (i.TotalAmount - i.WorkHouseOtherCosts) * ifnull(i.CurrencyRate, 1) TotalToPay
    , i.RemainingAmount * ifnull(i.CurrencyRate, 1) Balance
    , i.TotalRoundings * ifnull(i.CurrencyRate, 1) RoundOff
    , i.TotalAmount * ifnull(i.CurrencyRate, 1) Total
    , if(i.WorkHouseOtherCosts=0, FALSE, TRUE) HouseWork
    , iRows.ContributionValue
    , (
      select string_agg(comment, ' ')
      from unnest(ifnull(i.Notes, [])) comment
      where comment is not null
    ) Comments
    , i.ElectronicReference Remarks
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
    , i.OrgId || '-' || i.CustomerId CustomerId
    , fy.FinancialYearId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , cast(null as STRING) as PriceList
  from {{ source('visma_eaccounting_api', 'customerinvoices') }} i
    left join iRows on iRows.InvoiceId=i.OrgId || '-' || i.Id
    left join fy on i.InvoiceDate between fy.FromDate and fy.ToDate
)
select *
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'CustomerId', 'FinancialYearId', 'CostCenterId', 'ProjectId']) }}
from final