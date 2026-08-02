{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


with labels0 as (
  select 
    i.OrgId
    , i.DocumentNumber
    , coalesce(
        trim(l.Description) || ' (' || json_extract_scalar(r, '$.Id') || ')',
        json_extract_scalar(r, '$.Id')
      ) as Label
  from {{ ref('fortnox_base_v2_invoices') }} i
  , unnest(json_extract_array(Labels)) r
  left join {{ source('fortnox_api', 'labels') }} l
    on l.OrgId = i.OrgId
    and cast(l.Id as string) = json_extract_scalar(r, '$.Id')
  where json_extract_scalar(r, '$.Id') is not null
)

, labels as (
  select
    OrgId
    , DocumentNumber
    , string_agg(Label, ', ') Labels
  from labels0
  group by 1,2
)

select
  cast(i.DocumentNumber as int64) InvoiceNo
  , cast(i.OrgId as string) || '-' || cast(i.DocumentNumber as string) InvoiceId
  , date(InvoiceDate) InvoiceDate
  , date(OutboundDate) OutboundDate
  , date(DeliveryDate) DeliveryDate
  , date(DueDate) DueDate
  , if (DueDate < current_date() and Balance <> 0, TRUE, FALSE) IsDue
  , case
    when Sent IS FALSE then "NotSent"
    when Sent IS TRUE then case
      when Balance = 0 then "Paid"
      when Balance <> 0 then case
        when ABS(DATE_DIFF(current_date(), DueDate, day)) between 0
        and 15 then "0-15d"
        when ABS(DATE_DIFF(current_date(), DueDate, day)) between 16
        and 30 then "16-30d"
        when ABS(DATE_DIFF(current_date(), DueDate, day)) between 31
        and 45 then "31-45d"
        when ABS(DATE_DIFF(current_date(), DueDate, day)) between 46
        and 60 then "46-60d"
        when ABS(DATE_DIFF(current_date(), DueDate, day)) between 61
        and 90 then "61-90d"
        when ABS(DATE_DIFF(current_date(), DueDate, day)) between 91
        and 120 then "91-120d"
        when ABS(DATE_DIFF(current_date(), DueDate, day)) > 120 then ">120d"
        when DueDate is null then 'NO_DUE_DATE'
        else 'WHAT?'
      end
      else 'WOW??'
    end
    else "[calc_error]"
  end DueStatus
  , FinalPayDate
  , Reminders
  , date(LastRemindDate) LastRemindDate
  , Credit isCredit
  , initcap( {{ blank_to_null('OurReference') }} ) OurReference
  , initcap( {{ blank_to_null('YourReference') }} ) YourReference
  , trim({{ blank_to_null('YourOrderNumber') }}) YourOrderNumber
  , Sent
  , Currency
  , CurrencyRate
  , Gross * CurrencyRate Gross
  , Net * CurrencyRate Net
  , Freight * CurrencyRate Freight
  , AdministrationFee * CurrencyRate AdministrationFee
  , TotalVAT * CurrencyRate TotalVAT
  , TotalToPay * CurrencyRate TotalToPay
  , Balance * CurrencyRate Balance
  , RoundOff * CurrencyRate RoundOff
  , Total * CurrencyRate Total
  , HouseWork
  , ContributionValue
  , {{ blank_to_null('Comments') }} Comments
  , {{ blank_to_null('Remarks') }} Remarks
  , {{ blank_to_null("TermsOfDelivery") }} TermsOfDelivery
  , {{ blank_to_null("TermsOfPayment") }} TermsOfPayment
  , {{ blank_to_null("TermsOfPayment") }} WayOfDelivery
  , {{ blank_to_null("DeliveryAddress1") }} DeliveryAddress1
  , {{ blank_to_null("DeliveryAddress2") }} DeliveryAddress2
  , {{ blank_to_null("DeliveryCity") }} DeliveryCity
  , {{ blank_to_null("DeliveryCountry") }} DeliveryCountry
  , {{ blank_to_null("DeliveryZipCode") }} DeliveryZipCode
  , {{ blank_to_null("DeliveryName") }} DeliveryName
  , {{ blank_to_null("json_extract_scalar(EmailInformation, '$.EmailAddressTo')") }} RecipientEmail
  , {{ blank_to_null("Phone1") }} RecipientPhone
  , trim({{ blank_to_null('Country') }}) Country
  , {{blank_to_null('ExternalInvoiceReference1')}} ExternalInvoiceReference1
  , {{blank_to_null('ExternalInvoiceReference1')}} ExternalInvoiceReference2
  , {{blank_to_null('CreditInvoiceReference')}} CreditInvoiceReference 
  , {{blank_to_null('OCR')}} InvoiceOCR
  , OfferReference
  , OrderReference
  , cast(ContractReference as string) ContractReference
  , WarehouseReady isWarehouseReady
  , labels.Labels
  , i.OrgId
  , i.OrgId || '-' || {{ blank_to_null('CustomerNumber') }} CustomerId
  , i.OrgId || '-' || VoucherYear as FinancialYearId
  , i.OrgId || '-' || {{ blank_to_null('CostCenter') }} CostCenterId
  , i.OrgId || '-' || {{ blank_to_null('Project') }} ProjectId
  , {{blank_to_null('PriceList')}} PriceList
from {{ ref('fortnox_base_v2_invoices') }} i
left join labels
  on labels.OrgId = i.OrgId
  and labels.DocumentNumber = i.DocumentNumber
where cancelled is not true