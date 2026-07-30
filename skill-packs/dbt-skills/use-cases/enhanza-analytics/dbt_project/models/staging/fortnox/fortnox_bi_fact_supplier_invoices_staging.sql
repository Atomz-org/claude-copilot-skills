{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


select
  InvoiceDate
  , DueDate
  , case
    when cast(Balance as FLOAT64) = 0 then "Paid"
    when cast(Balance as FLOAT64) <> 0 then
      case
        when abs(date_diff(current_date(), DueDate, DAY)) between 0 and 15 then "0-15d"
        when abs(date_diff(current_date(), DueDate, DAY)) between 16 and 30 then "16-30d"
        when abs(date_diff(current_date(), DueDate, DAY)) between 31 and 45 then "31-45d"
        when abs(date_diff(current_date(), DueDate, DAY)) between 46 and 60 then "46-60d"
        when abs(date_diff(current_date(), DueDate, DAY)) between 61 and 90 then "61-90d"
        when abs(date_diff(current_date(), DueDate, DAY)) between 91 and 120 then "91-120d"
        when abs(date_diff(current_date(), DueDate, DAY)) > 120 then ">120d"
        when DueDate is null then 'NO_DUE_DATE'
        else 'WHAT?'
      end
    else 'WOW??'
  end DueStatus
  , FinalPayDate
  , GivenNumber SupplierInvoiceNo
  , InvoiceNumber
  , Currency
  , Total * CurrencyRate Total
  , Vat * CurrencyRate Vat
  , AdministrationFee * CurrencyRate AdministrationFee
  , Freight * CurrencyRate Freight
  , cast(Balance as FLOAT64) * CurrencyRate Balance
  , Credit isCredit
  , Booked isBooked
  , DisablePaymentFile
  , {{blank_to_null('YourReference') }} YourReference
  , {{blank_to_null('OurReference') }} OurReference
  , OrgId
  , OrgId || '-' || {{ blank_to_null('GivenNumber') }} SupplierInvoiceId
  , OrgId || '-' || {{ blank_to_null('SupplierNumber') }} SupplierId
  , OrgId || '-' || {{ blank_to_null('CostCenter') }} CostCenterId
  , OrgId || '-' || {{ blank_to_null('Project') }} ProjectId
from {{ source('fortnox_api', 'supplier_invoices') }}
where Cancelled is FALSE