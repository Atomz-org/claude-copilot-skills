{{ config(materialized='ephemeral', enabled = var('is_tripletex_enabled', false)) }}

with BAS as (
  select
    cast(Account as string) AccountString
    , AccountClass
    , MainAccount
    , SubAccount
  from {{ source('public', 'bas_account_chart') }}
)

, fy as (
  select
    OrgId
    , OrgId || '-' || id FinancialYearId
    , date(`start`) FromDate
  from {{ source('tripletex_api', 'annual_account') }}
)

, balance as (
  select
    OrgId
    , json_extract_scalar(account, '$.id') AccountId
    , balanceIn BalanceBroughtForward
    , balanceOut BalanceCarriedForward
    , startDate
  from {{ source('tripletex_api', 'balance_sheet') }}
)
, final as (
  select
    cast(a.Number as INT) as Number
    , trim(a.name) AccountName
    , bs.BalanceBroughtForward
    , bs.BalanceCarriedForward
    , a.OrgId || '-' || json_extract_scalar(a.department, '$.id') CostCenterId
    , cast(null as STRING) as ProjectId
    , left(b1.AccountString, 1) AccountClassId
    , max(b1.AccountClass) AccountClass
    , left(b2.AccountString, 2) MainAccountId
    , max(b2.MainAccount) MainAccount
    , left(b3.AccountString, 3) SubAccountId
    , max(b3.SubAccount) SubAccount
    , cast(null as STRING) as VATCode
    , fy.FinancialYearId || '-' || a.number AccountId
    , cast(null as STRING) as AccountIdVoucher
    , fy.FinancialYearId
  from {{ source('tripletex_api', 'account') }} a
  inner join fy on fy.OrgId = a.OrgId
  left join balance bs
    on bs.startDate = date(fy.FromDate)
    and bs.OrgId = a.OrgId
    and bs.AccountId = cast(id as string)
  left join BAS b1
    on left(b1.AccountString, 1) = left(a.numberPretty, 1)
  left join BAS b2
    on left(b2.AccountString, 2) = left(a.numberPretty, 2)
  left join BAS b3
    on left(b3.AccountString, 3) = left(a.numberPretty, 3)
  group by 1,2,3,4,5,6,7,9,11,13,14,15,16
)

select *
, {{ add_erp_fields(columns=['AccountId', 'FinancialYearId']) }}
from final