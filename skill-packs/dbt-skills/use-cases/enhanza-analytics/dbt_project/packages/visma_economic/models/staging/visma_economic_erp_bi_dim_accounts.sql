{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with x as (
  select
    distinct left(cast(Account as string), 1) AccountClassId
    , AccountClass
    , Bas
  from {{ source('public', 'bas_account_chart') }}
)
, xx as (
  select
    distinct left(cast(Account as string), 2) MainAccountId
    , MainAccount
    , Bas
  from {{ source('public', 'bas_account_chart') }}
)
, xxx as (
  select
    distinct left(cast(Account as string), 3) SubAccountId
    , SubAccount
    , Bas
  from {{ source('public', 'bas_account_chart') }}
)
, final as (
  select
    cast(a.accountNumber as INT) as Number
    , name AccountName
    , 0.00 as BalanceBroughtForward
    , 0.00 as BalanceCarriedForward
  --, balance BalanceBroughtForward
  --need additional development in terms of vouchers
  --round(BalanceBroughtForward - ifnull(v.Balance, 0), 2) BalanceCarriedForward
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , left(cast(a.accountNumber as string), 1) AccountClassId
    , x.AccountClass
    , left(cast(a.accountNumber as string), 2) MainAccountId
    , xx.MainAccount
    , left(cast(a.accountNumber as string), 3) SubAccountId
    , xxx.SubAccount
    , cast(null as STRING) as VATCode
    , OrgId || '-' || cast(json_extract_scalar(ay, '$.year') as int64) || '-' || a.accountNumber AccountId
    , cast(null as string) as AccountIdVoucher
    , cast(null as string) as FinancialYearId
  from
    {{ source('visma_economic_api', 'accounts') }} a
    , unnest(cast(json_extract_array(accountingYears) as array<JSON>)) ay
    left join x on left(cast(a.accountNumber as string), 1) = x.AccountClassId
    left join xx on left(cast(a.accountNumber as string), 2) = xx.MainAccountId
    left join xxx on left(cast(a.accountNumber as string), 3) = xxx.SubAccountId
)

select *
, {{ add_erp_fields(columns=['AccountId', 'FinancialYearId']) }}
from final