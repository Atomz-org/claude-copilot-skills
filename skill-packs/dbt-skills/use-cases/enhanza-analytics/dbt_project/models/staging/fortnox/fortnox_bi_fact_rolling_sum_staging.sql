{{ config(alias='fortnox_bi_rolling_sum', enabled = source_is_enabled(model.name)) }}

with month_array as (
  -- Create an array of month dates (last day) for the past 5 years.
  select
    distinct Month
  from
    (
      Select
        distinct LAST_DAY(Date_trunc(Dt, Month)) as Month
      from
        Unnest(
          Generate_date_array(
            date_sub(current_date(), interval 5 year),
            current_date()
          )
        ) as Dt
    )
),
v0 as (
  select
    OrgId,
    r.Credit - r.Debit Balance,
    r.Account,
    coalesce(v.OrgId || '-' || if(r.CostCenter = "", null, r.CostCenter), 'null') as CostCenterId,
    date(v.TransactionDate) as TransactionDate
  from
    {{ source('fortnox_api', 'vouchers') }} v,
    UNNEST(VoucherRows) r
  where
  r.removed is not true
),
accountxmonth as (
  -- Repeat OrgId, Account and CostCenterId for each month
  Select
    distinct v0.OrgId,
    m.Month,
    v0.Account,
    coalesce(v0.CostCenterId, 'null') CostCenterId
  from
    v0
    cross join month_array m
  where
    v0.Account between 3000
    and 8999
    and TransactionDate > date_sub(current_date(), interval 5 year)
),
Raw_data as (
  -- Sum balance per dimension.
  SELECT
    OrgId,
    LAST_DAY(TransactionDate) as lastday,
    Account,
    coalesce(CostCenterId, 'null') CostCenterId,
    sum(Balance) as Amount
  FROM
    v0
  where
    Account between 3000
    and 8999
    and TransactionDate > date_sub(current_date(), interval 5 year)
  group by
    1,
    2,
    3,
    4
),
combine as (
  -- Merge date array with summed balance.
  Select
    distinct A.OrgId,
    A.Month,
    A.Account,
    A.CostCenterId,
    case
      when B.lastday is null then null
      else B.Amount
    end as Amount
  from
    accountxmonth A
    left join Raw_data B on A.Month = B.lastday
    and A.OrgId = B.OrgId
    and A.Account = B.Account
    and A.CostCenterId = B.CostCenterId
),
fy as (
  select
    OrgId,
    OrgId || '-' || Id as FinancialYearId,
    Id,
    FromDate,
    ToDate
  from
    {{ source('fortnox_api', 'financial_years') }}
)
Select
  -- 12 months rolling sum
  c.OrgId,
  c.Month,
  fy.FinancialYearId || '-' || c.Account as AccountId,
  c.CostCenterId,
  fy.FinancialYearId,
  coalesce(
    sum(Amount) over (
      partition by c.OrgId,
      c.Account,
      c.CostCenterId
      order by
        Month Rows BETWEEN 11 PRECEDING
        AND CURRENT ROW
    ),
    Amount
  ) as rolling_sum
from
  combine c
  left join fy on c.OrgId = fy.OrgId
  and c.Month between fy.FromDate
  and fy.ToDate