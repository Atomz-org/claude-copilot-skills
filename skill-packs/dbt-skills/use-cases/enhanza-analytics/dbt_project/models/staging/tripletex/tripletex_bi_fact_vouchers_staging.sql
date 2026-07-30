{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with fy as (
  select
    OrgId || '-' || id FinancialYearId
    , OrgId
    , date(`start`) FromDate
  -- in Tripletex, dates are from yyyy-01-01 to yyyy-01-01 which makes 1st January ambiguous
    , case
      when extract(day from `start`) <> extract(day from `end`) then date(`end`)
      else date_sub(`end`, INTERVAL 1 day)
    end ToDate
  from {{ source('tripletex_api', 'annual_account') }}
)

, acc as (
  select
    OrgId
    , cast(id as string) AccountId
    , number Account
  from {{ source('tripletex_api', 'account') }}
)

, vouchers as (
  select
    lv.OrgId
    , cast(lv.id as string) VoucherId
    , lv.number VoucherNumber
    , vt.displayName VoucherSeries
  from {{ source('tripletex_api', 'ledger_voucher') }} lv
  left join {{ source('tripletex_api', 'voucher_type') }} vt
    on vt.OrgId = lv.OrgId
    and cast(vt.id as string) = json_extract_scalar(lv.voucherType, '$.id')
)
select
  date(lp.date) TransactionDate
  , acc.Account
  , amount Amount --amount is in NOK, amountCurrency is in original currency
  , trim(lp.description) Description
  , v.VoucherSeries
  , v.VoucherNumber
  , {{ blank_to_null('lp.invoiceNumber') }} ReferenceNumber
  , lp.OrgId
  , fy.FinancialYearId
  , fy.FinancialYearId || '-' || acc.Account AccountId
  , lp.OrgId || '-' || json_extract_scalar(lp.department, '$.id') CostCenterId
  , lp.OrgId || '-' || json_extract_scalar(lp.project, '$.id') ProjectId
  , lp.OrgId || '-' || json_extract_scalar(lp.voucher, '$.id') VoucherSeriesId
  , lp.OrgId || '-' || json_extract_scalar(lp.customer, '$.id') CustomerId
  , lp.OrgId || '-' || json_extract_scalar(lp.supplier, '$.id') SupplierId
from {{ source('tripletex_api', 'ledger_posting') }} lp
left join acc
  on acc.OrgId = lp.OrgId
  and acc.AccountId = json_extract_scalar(lp.account, '$.id')
left join vouchers v
  on v.OrgId = lp.OrgId
  and v.VoucherId = json_extract_scalar(lp.voucher, '$.id')
left join fy
  on fy.OrgId = lp.OrgId
  and date(lp.date) between fy.FromDate and fy.ToDate