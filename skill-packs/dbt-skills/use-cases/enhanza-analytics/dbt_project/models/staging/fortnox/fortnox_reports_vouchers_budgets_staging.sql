{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

with fy as (
  select
    FinancialYearId,
    FinancialYear,
    FyCounter,
    last_day(a) as Month
  from
    {{ ref('fortnox_bi_dim_financial_years_staging') }}
    cross join UNNEST(
      GENERATE_DATE_ARRAY(FromDate, ToDate, INTERVAL 1 MONTH)
    ) a
),
v as (
  with vouchers as (
    select
      OrgId,
      FinancialYearId,
      AccountId,
      CostCenterId,
      last_day(TransactionDate) as TransactionMonth,
      sum(Balance) as Balance
    from
      {{ ref('fortnox_bi_fact_vouchers_staging') }}
    where
      Account between 3000
      and 8999
    group by
      OrgId,
      FinancialYearId,
      AccountId,
      CostCenterId,
      last_day(TransactionDate),
      Account
  )
  select
    OrgId,
    FinancialYearId,
    AccountId,
    CostCenterId,
    TransactionMonth,
    sum(v.Balance) as Balance
  from
    vouchers v
  group by
    1,
    2,
    3,
    4,
    5
),
b as (
  select
    OrgId,
    FinancialYearId,
    AccountId,
    CostCenterId,
    BudgetDate as Month,
    sum(Amount) Budget
  from
    {{ ref('fortnox_bi_fact_budgets_staging') }}
  group by
    OrgId,
    FinancialYearId,
    AccountId,
    CostCenterId,
    Month
)
select
  c.OrgId,
  c.OrgName,
  fy.FinancialYear,
  fy.FyCounter,
  coalesce(v.TransactionMonth, b.Month) as Month,
  ifnull(a.Number, 0) as AccountNumber,
  a.AccountName,
  /*concat(
  "(",
  a.AccountClassId,
  ") ",
  AccountClass
  ) as AccountClass,*/
  case
  when CAST(a.Number as INTEGER) between 1000 and 1999 then "1. Tillgångar" --1. Assets
  when CAST(a.Number as INTEGER) between 2000 and 2999 then "2. Eget kapital och skulder" --2. Equity and Liabilities
  when CAST(a.Number as INTEGER) between 3000 and 3999 then "3. Intäkter" --3. Operating income/revenue
  when CAST(a.Number as INTEGER) between 4000 and 4999 then "4. Materialkostnader" --4. Cost of goods
  when CAST(a.Number as INTEGER) between 5000 and 6999 then "5-6. Övriga kostnader" --5-6. Other external costs
  when CAST(a.Number as INTEGER) between 7000 and 7999 then "7. Personal" --7. Personnel costs
  when CAST(a.Number as INTEGER) between 8000 and 8999 then "8. Finansiella intäkter/kostnader" --8. Financials
  ELSE CAST(a.Number as STRING)
  END AccountClass,
  concat(
    "(",
    a.MainAccountId,
    ") ",
    MainAccount
  ) as AccountGroup,
  ifnull(cc.Description, "[inget]") as CostCenter,
  cc.Code as CostCenterCode,
  ifnull(v.Balance, 0) as Balance,
  ifnull(b.Budget, 0) as Budget,
from
  v full
  outer join b on v.OrgId = b.OrgId
  and v.TransactionMonth = b.Month
  and ifnull(v.CostCenterID, 'null') = ifnull(b.CostCenterId, 'null')
  and v.AccountId = b.AccountId
  left join fy on coalesce(v.TransactionMonth, b.Month) = fy.Month
  and coalesce(v.FinancialYearId, b.FinancialYearId) = fy.FinancialYearId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on cc.CostCenterId = coalesce(v.CostCenterId, b.CostCenterId)
  left join {{ ref('fortnox_bi_dim_company_staging') }} c on c.OrgId = coalesce(v.OrgId, b.OrgId)
  left join {{ ref('fortnox_bi_dim_accounts_staging') }} a on a.AccountId = coalesce(v.AccountId, b.AccountId)
where
  (
    v.Balance is not null
    or b.Budget is not null
  )