{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

with accounts as (
  with months as (
    -- create an array of dates per the end of each month from all financial years.
    select
      OrgId,
      FinancialYearId,
      FinancialYear,
      FyCounter,
      last_day(m) month_last_day
    from
      {{ ref('fortnox_bi_dim_financial_years_staging') }}
      cross join unnest(
        GENERATE_DATE_ARRAY(FromDate, ToDate, interval 1 month)
      ) as m
  )
  select
    -- List all accounts with their BalanceBroughtForward and sum of balance from vouchers.
    m.OrgId,
    m.FinancialYearId,
    m.FinancialYear,
    m.FyCounter,
    m.month_last_day Month,
    a.Number Account,
    a.AccountName,
    case
  when CAST(a.Number as INTEGER) between 1000 and 1999 then "1. Tillgångar" --1. Assets
  when CAST(a.Number as INTEGER) between 2000 and 2999 then "2. Eget kapital och skulder" --2. Equity and Liabilities
  when CAST(a.Number as INTEGER) between 3000 and 3999 then "3. Intäkter" --3. Operating income/revenue
  when CAST(a.Number as INTEGER) between 4000 and 4999 then "4. Materialkostnader" --4. Cost of goods
  when CAST(a.Number as INTEGER) between 5000 and 6999 then "5-6. Övriga kostnader" --5-6. Other external costs
  when CAST(a.Number as INTEGER) between 7000 and 7999 then "7. Personal" --7. Personnel costs
  when CAST(a.Number as INTEGER) between 8000 and 8999 then "8. Finansiella intäkter/kostnader" --8. Financials
  ELSE CAST(a.Number as STRING)
  END as AccountClass,
    concat(a.MainAccountId,". ", a.MainAccount) as MainAccount,
    ifnull(sum(Balance) * -1, 0) Balance,
    BalanceBroughtForward
  from
    months m
    left join {{ ref('fortnox_bi_dim_accounts_staging') }}  a on m.FinancialYearId = a.FinancialYearId
    left join {{ ref('fortnox_bi_fact_vouchers_staging') }} v on v.Account = a.Number
    and v.FinancialYearId = m.FinancialYearId
    and last_day(v.TransactionDate) = m.month_last_day
  where
    a.Number between 1000
    and 2999
  group by
    m.OrgId,
    m.FinancialYearId,
    m.FinancialYear,
    m.FyCounter,
    a.Number,
    a.AccountName,
    AccountClass,
    MainAccount,
    Month,
    a.BalanceBroughtForward
)
select
  a.OrgId,
  cs.OrgName,
  a.FinancialYear,
  a.FyCounter,
  a.Month,
  a.Account as AccountNumber,
  a.AccountName,
  a.AccountClass,
  a.MainAccount,
  a.BalanceBroughtForward,
  sum(a.balance) over (
    partition by a.FinancialYearId,
    a.Account
    order by
      Month
  ) + a.BalanceBroughtForward - a.balance as PeriodOpeningBalance,
  balance PeriodBalance,
  sum(balance) over (
    partition by FinancialYearId,
    Account
    order by
      Month
  ) + BalanceBroughtForward as BalanceCarriedForward
from
  accounts a
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs on a.OrgId = cs.OrgId