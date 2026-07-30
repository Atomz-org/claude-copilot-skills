{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  TransactionDate
  , Account
  , Amount as Balance --amount is in NOK, amountCurrency is in original currency
  , Description
  , VoucherSeries
  , VoucherNumber
  , ReferenceNumber
  , OrgId
  , FinancialYearId
  , AccountId
  , CostCenterId
  , ProjectId
  , VoucherSeriesId
  , CustomerId
  , SupplierId
from {{ ref('tripletex_bi_fact_vouchers_staging') }}