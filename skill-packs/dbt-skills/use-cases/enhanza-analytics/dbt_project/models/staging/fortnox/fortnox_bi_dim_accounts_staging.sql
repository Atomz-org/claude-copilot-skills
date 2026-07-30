{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with v0 as (
  select
    r.Credit - r.Debit Balance,
    v.OrgId || '-' || v.Year FinancialYearId,
    v.OrgId || '-' || v.Year || '-' || r.Account as AccountId
  from
    {{ source('fortnox_api', 'vouchers') }} v,
    UNNEST(VoucherRows) r
  where
    r.removed is not true
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
    AccountClass,
    Bas
  from
    {{ source('public', 'bas_account_chart') }}
),
xx as (
  select
    distinct left(cast(Account as string), 2) as MainAccountId,
    MainAccount,
    Bas
  from
    {{ source('public', 'bas_account_chart') }}
),
xxx as (
  select
    distinct left(cast(Account as string), 3) as SubAccountId,
    SubAccount,
    Bas
  from
    {{ source('public', 'bas_account_chart') }}
)
select
  Number,
  Description as AccountName,
  BalanceBroughtForward,
  -- BalanceCarriedForward, INFO: BalanceCarriedForward from Fortnox API is not updated. Calculated below instead.
  round(BalanceBroughtForward - ifnull(v.Balance, 0), 2) as BalanceCarriedForward,
  --${mappings.accountClassMapping("Number")} AccountClass,
  OrgId || '-' || {{ blank_to_null('CostCenter') }} as CostCenterId,
  OrgId || '-' || {{ blank_to_null('Project') }} as ProjectId,
  left(cast(a.Number as string), 1) as AccountClassId,
  x.AccountClass,
  left(cast(a.Number as string), 2) as MainAccountId,
  xx.MainAccount,
  left(cast(a.Number as string), 3) as SubAccountId,
  xxx.SubAccount,
  {{ blank_to_null('a.VATCode') }} VATCode,
  OrgId || '-' || Year || '-' || Number as AccountId,
  cast(null as string) as AccountIdVoucher,
  OrgId || '-' || Year FinancialYearId
from
  {{ source('fortnox_api', 'accounts') }} a
  left join v on a.OrgId || '-' || a.Year || '-' || a.Number = v.AccountId
  --left join ${ref("bas_account_chart")} b on cast(a.Number as string) = b.Account
  left join x on left(cast(a.Number as string), 1) = x.AccountClassId
  left join xx on left(cast(a.Number as string), 2) = xx.MainAccountId
  left join xxx on left(cast(a.Number as string), 3) = xxx.SubAccountId
where
  Active is true
