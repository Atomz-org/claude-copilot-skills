{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

With Precalculations as (
  Select
    OrgId,
    FinancialYear,
    LAST_DAY(PARSE_DATE("%Y%m", Month)) as BudgetDate,
    AccountId as Account,
    ObjectId,
    sum(Amount) * (-1) as Amount
  from
   {{ source('fortnox_api', 'budgets') }}
  group by
    1,
    2,
    3,
    4,
    5
)
Select
OrgId,BudgetDate,Account,
  CASE
    WHEN objectid IS NULL THEN (Amount*2 - SUM(Amount) OVER (PARTITION BY OrgId,FinancialYear, BudgetDate, Account))
  ELSE
  Amount
END
  AS Amount,
  OrgId || '-' || FinancialYear || '-' || {{ blank_to_null('Account') }} as AccountId,
  OrgId || '-' || FinancialYear as FinancialYearId,
  OrgId || '-' || {{ blank_to_null('ObjectId') }} as CostCenterId
from
  Precalculations