{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'visma_eaccounting', 'visma_economic'])
) }}

with accounts as (
  with accounts_active_dates as (
      -- we get range of active dates for each account, based on vouchers tables
      select Account, OrgId, min(TransactionDate) account_active_since
      from {{ ref('erp_bi_fact_vouchers') }} v2
      where DataSource != "Tripletex"
      group by Account, OrgId
    ),
    dates as (
    -- create an array of dates from all financial years.
    select
      OrgId,
      FinancialYearIdERP FinancialYearId,
      m as date_
    from
      {{ ref('erp_bi_dim_financial_years') }}
      cross join unnest(
        GENERATE_DATE_ARRAY(FromDate, ToDate, interval 1 day)
      ) as m
      where DataSource != "Tripletex"
    ),
    accounts_x_days as (
    -- multiply accounts on each day from existing fin years
      select Account, FinancialYearId, a.OrgId, d.date_ as Date from accounts_active_dates a join dates d on a.account_active_since <= d.date_ and a.OrgId = d.OrgId
    ),
    vouchers_prep as (
     select a.Date, a.FinancialYearId, a.Account, a.OrgId, vv.VoucherSeries, vv.VoucherNumber, vv.TransactionInformation, vv.DescriptionRows, vv.Description, vv.Amount
     from accounts_x_days a
     left join {{ ref('erp_bi_fact_vouchers') }} vv on a.Date = vv.TransactionDate and a.Account = vv.Account and a.OrgId = vv.OrgId and vv.DataSource != "Tripletex"
    ),
    vouchers_with_runnin_sum as (
      select a.Date as TransactionDate, a.FinancialYearId, a.Account, a.OrgId, a.VoucherSeries, a.VoucherNumber, a.TransactionInformation, a.DescriptionRows, a.Description, a.Amount,
      sum(ifnull(v2.Amount, 0) * -1) as RunningFinYearBalance
      from vouchers_prep a
      left join  {{ ref('erp_bi_fact_vouchers') }} v2
      on a.Account = v2.Account
      and a.OrgId = v2.OrgId
      and a.FinancialYearId = v2.FinancialYearIdERP
      -- we get complete balance up to previous day to use it as opening balance
      and v2.TransactionDate < a.Date
      and v2.DataSource != 'Tripletex'
     group by a.Date, a.FinancialYearId, a.Account, a.OrgId, a.VoucherSeries, a.VoucherNumber, a.TransactionInformation, a.DescriptionRows, a.Description, a.Amount
    )
  select
    -- List all accounts with their BalanceBroughtForward and sum of balance from vouchers.
    m.OrgId,
    m.FinancialYearId,
    last_day(m.TransactionDate) Month,
    m.TransactionDate,
    m.VoucherSeries,
    m.VoucherNumber,
    m.TransactionInformation,
    m.DescriptionRows,
    m.Description,
    a.Number Account,
    a.AccountIdERP AccountId,
    cxm.CategoryId || '|' || cxm.Level2ID AccountCategoryBreakdownID,
    a.DataSource,
    a.DefaultCurrency,
    ifnull(sum(m.Amount) * -1, 0) Balance,
    a.BalanceBroughtForward,
    m.RunningFinYearBalance
  from
    vouchers_with_runnin_sum m
    left join {{ ref('erp_bi_dim_accounts') }} a
      on m.FinancialYearId = a.FinancialYearIdERP
      and m.Account = a.Number
    -- joining global chart of accounts and current mapping to get new filtering
    left join {{ ref('categories_x_mapping') }} cxm
      on cxm.DimensionIdERP = split(a.AccountId, '-')[offset(0)] || '-' || a.Number
  where
    cxm.Level1ID in ('1-1001', '1-1002') -- assets and equity
  group by
     m.OrgId,
    m.FinancialYearId,
    last_day(m.TransactionDate),
    m.TransactionDate,
    m.VoucherSeries,
    m.VoucherNumber,
    m.TransactionInformation,
    m.DescriptionRows,
    m.Description,
    a.Number,
    a.AccountIdERP,
    cxm.CategoryId || '|' || cxm.Level2ID,
    a.DataSource,
    a.DefaultCurrency,
    a.BalanceBroughtForward,
    m.RunningFinYearBalance
)
select
  a.Month
  , TransactionDate
  , a.BalanceBroughtForward + ifnull(RunningFinYearBalance,0) as PeriodOpeningBalance
  , balance PeriodBalance
  -- same as PeriodOpeningBalance, but added running sum for current date, vouchers ordered
  , sum(balance) over (partition by FinancialYearId, Account, Month, TransactionDate) + a.BalanceBroughtForward + ifnull(RunningFinYearBalance,0) as BalanceCarriedForward
  , a.VoucherSeries
  , a.VoucherNumber
  , a.TransactionInformation
  , a.DescriptionRows
  , a.Description
  , cast(a.OrgId as string) as OrgId
  , a.AccountId
  , AccountCategoryBreakdownID
  , FinancialYearId
  , a.DataSource
  , a.DefaultCurrency
from
  accounts a