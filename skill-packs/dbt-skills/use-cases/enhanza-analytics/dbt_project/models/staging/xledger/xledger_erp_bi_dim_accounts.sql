{{ config(materialized='ephemeral', enabled = var('is_xledger_enabled', false)) }}

with x as (
  select
    distinct left(cast(Account as string), 1) as AccountClassId,
    AccountClass,
    Bas
  from
    {{ source('public', 'bas_account_chart') }}
)
, xx as (
  select
    distinct left(cast(Account as string), 2) as MainAccountId,
    MainAccount,
    Bas
  from
    {{ source('public', 'bas_account_chart') }}
)
, xxx as (
  select
    distinct left(cast(Account as string), 3) as SubAccountId,
    SubAccount,
    Bas
  from
    {{ source('public', 'bas_account_chart') }}
)

-- chartOfAccountDbId=2   NS4102, has * at the end
-- chartOfAccountDbId=3   BAS2017
-- chartOfAccountDbId=4   USSTD
-- chartOfAccountDbId=6   UKSTD
-- chartOfAccountDbId=8   DKSTD
-- chartOfAccountDbId=12  FINACC have 5 digits
-- chartOfAccountDbId=15  FINACCN have 4-5 digits and sometimes letters

, final as (
  select
    cast(REGEXP_REPLACE(code, r'[^0-9]', '') as INT) as Number -- needs to be checked if * part of 3 Numbers are needed
    , description AccountName
    , 0.00 as BalanceBroughtForward
    , 0.00 as BalanceCarriedForward
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , left(cast(code as string), 1) AccountClassId
    , x.AccountClass
    , left(cast(code as string), 2) MainAccountId
    , xx.MainAccount
    , left(cast(code as string), 3) SubAccountId
    , xxx.SubAccount
    , cast(null as STRING) as VATCode
    , OrgId || '-' || dbId AccountId
    , cast(null as string) as AccountIdVoucher
    , cast(null as STRING) as FinancialYearId
from
  {{ source('xledger_api', 'accounts') }} a
left join x 
  on left(cast(code as string), 1) = x.AccountClassId and chartOfAccountDbId=3
left join xx 
  on left(cast(code as string), 2) = xx.MainAccountId  and chartOfAccountDbId=3
left join xxx 
  on left(cast(code as string), 3) = xxx.SubAccountId  and chartOfAccountDbId=3
)

select *
, {{ add_erp_fields(columns=['AccountId', 'FinancialYearId']) }}
from final