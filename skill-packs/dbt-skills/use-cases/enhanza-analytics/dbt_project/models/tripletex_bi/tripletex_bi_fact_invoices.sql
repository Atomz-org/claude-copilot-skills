{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  InvoiceNo
  , InvoiceId
  , InvoiceDate
  , DeliveryDate
  , DueDate
  , IsDue
  , DueStatus
  , Reminders
  , isCredit
  , Sent
  , Currency
  , CurrencyRate
  , Net
  , TotalVAT
  , TotalToPay
  , Balance
  , RoundOff
  , Total
  , Comments
  , Remarks
  , CreditInvoiceReference
  , InvoiceOCR
  , OrgId
  , CustomerId
from {{ ref('tripletex_bi_fact_invoices_staging') }}