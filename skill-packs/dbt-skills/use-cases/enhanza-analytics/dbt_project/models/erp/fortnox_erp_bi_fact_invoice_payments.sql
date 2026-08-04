{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  OrgId
  , InvoiceNo
  , InvoiceId
  , isBooked
  , Net
  , PaymentDate
  , ModeOfPayment
  , Number
  , Source
  , InvoiceOCR
  , VoucherNumber
  , VoucherSeriesId
  , ModeOfPaymentAccountId
  , CustomerId
  , Currency
  , CurrencyRate
  , NetOriginalCurrency
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'VoucherSeriesId', 'ModeOfPaymentAccountId', 'CustomerId']) }}
from {{ ref('fortnox_bi_fact_invoice_payments_staging') }}
