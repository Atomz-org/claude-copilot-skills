{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with fy as ( --fiscalyears source snapshot
  SELECT
    OrgId || '-' || Id FinancialYearId
    , OrgId
    , StartDate FromDate
    , EndDate ToDate
  FROM
    {{ source('visma_eaccounting_api', 'fiscalyears') }}
)

, balances as (
  select
    b.OrgId
    , b.Number Account
    , b.Balance OpeningBalance
    , fy.FinancialYearId
  from {{ source('visma_eaccounting_api', 'openingbalances') }} b
  left join fy
    on date(coalesce(b.ENZ_MODIFIED_AT, b.ENZ_CREATED_AT)) between fy.FromDate and fy.ToDate
    and b.OrgId=fy.OrgId
)

, v0 as ( --vouchers source snapshot
  select
    cast(json_extract_scalar(r, '$.CreditAmount') as numeric)-cast(json_extract_scalar(r, '$.DebitAmount') as numeric) Balance
    , fy.FinancialYearId  
    , fy.FinancialYearId || '-' || json_extract_scalar(r, '$.AccountNumber') AccountId
  from
    {{ source('visma_eaccounting_api', 'vouchers') }} v
    , UNNEST(CAST(JSON_EXTRACT_ARRAY(v.Rows) AS ARRAY<JSON>)) r
  left join fy on v.VoucherDate between fy.FromDate and fy.ToDate and fy.OrgId=v.OrgId
)

, v as (
  select
    sum(Balance) as Balance,
    AccountId
  from
    v0
  group by
    FinancialYearId,
    AccountId
),
x as (
  select
    distinct left(cast(Account as string), 1) as AccountClassId,
    AccountClass
  from
    {{ source('public', 'bas_account_chart') }}
),
xx as (
  select
    distinct left(cast(Account as string), 2) as MainAccountId,
    MainAccount
  from
    {{ source('public', 'bas_account_chart') }}
),
xxx as (
  select
    distinct left(cast(Account as string), 3) as SubAccountId,
    SubAccount
  from
    {{ source('public', 'bas_account_chart') }}
)

, final as (
  select
    cast(a.Number as INT) as Number
    , a.Name AccountName
    , b.OpeningBalance BalanceBroughtForward
    , round(ifnull(b.OpeningBalance, 0) - ifnull(v.Balance, 0), 2) BalanceCarriedForward
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , left(a.Number, 1) AccountClassId
    , x.AccountClass
    , left(a.Number, 2) MainAccountId
    , xx.MainAccount
    , left(a.Number, 3) SubAccountId
    , xxx.SubAccount
    , cast(null as STRING) as VATCode
    , a.OrgId || '-' || a.FiscalYearId || '-' || a.Number AccountId
  --, a.OrgId || '-' || a.FiscalYearId || '-' || a.Number AccountIdVoucher
    , cast(null as string) as AccountIdVoucher
    , a.OrgId || '-' || a.FiscalYearId as FinancialYearId
  from
    {{ source('visma_eaccounting_api', 'accounts') }} a
  left join v
    on a.OrgId || '-' || a.FiscalYearId || '-' || a.Number = v.AccountId
  left join x 
    on left(cast(a.Number as string), 1) = x.AccountClassId
  left join xx 
    on left(cast(a.Number as string), 2) = xx.MainAccountId
  left join xxx 
    on left(cast(a.Number as string), 3) = xxx.SubAccountId
  left join balances b 
    on b.FinancialYearId=a.OrgId || '-' || a.FiscalYearId 
    and b.Account=cast(a.Number as INT)
  where
    IsActive is true
)

select *
, {{ add_erp_fields(columns=['AccountId', 'FinancialYearId']) }}
from final


