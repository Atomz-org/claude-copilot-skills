{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId
  , parse_numeric(InvoiceNumber) InvoiceNo
  , OrgId || '-' || {{ blank_to_null('InvoiceNumber') }} InvoiceId
  , Booked isBooked
  -- , parse_numeric(Amount) * parse_numeric(CurrencyRate) / parse_numeric(CurrencyUnit) Net
  , parse_numeric(Amount) Net
  , date(PaymentDate) PaymentDate
  , trim({{blank_to_null('ModeOfPayment')}}) ModeOfPayment
  , parse_numeric(Number) Number
  , initcap(trim({{blank_to_null('Source')}})) Source
  , trim({{blank_to_null('InvoiceOCR')}}) InvoiceOCR
  , trim({{blank_to_null('VoucherNumber')}}) VoucherNumber
  , OrgId || '-' || {{ blank_to_null('VoucherYear') }} || '-' || {{ blank_to_null('VoucherSeries') }} VoucherSeriesId
  , ModeOfPayment || '-' || {{ blank_to_null('ModeOfPaymentAccount') }} ModeOfPaymentAccountId
  , OrgId || '-' || {{ blank_to_null('InvoiceCustomerNumber') }} CustomerId
  , Currency
  , case
    when parse_numeric(CurrencyRate) <> 1 then parse_numeric(CurrencyRate)
    else parse_numeric(Amount) / nullif(parse_numeric(AmountCurrency), 0)
  end CurrencyRate
  , parse_numeric(AmountCurrency) NetOriginalCurrency
from {{ source('fortnox_api', 'invoice_payments') }}
