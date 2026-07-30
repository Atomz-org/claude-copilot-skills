{{ config(alias='fortnox_reports_rolling_sum', enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

SELECT
  r.OrgId,
  c.OrgName,
  r.* EXCEPT(OrgId,
    AccountId,
    CostCenterId,
    FinancialYearId),
  a.Number AS AccountNumber,
  a.AccountName,
  fy.FinancialYear,
  cc.Description AS CostCenter
FROM
  {{ ref('fortnox_bi_fact_rolling_sum_staging') }} r
LEFT JOIN
  {{ ref('fortnox_bi_dim_company_staging') }} c
ON
  r.OrgId = c.OrgId
LEFT JOIN
  {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc
ON
  r.CostCenterId = cc.CostCenterId
LEFT JOIN
  {{ ref('fortnox_bi_dim_accounts_staging') }} a
ON
  r.AccountId = a.AccountId
LEFT JOIN
  {{ ref('fortnox_bi_dim_financial_years_staging') }} fy
ON
  r.FinancialYearId = fy.FinancialYearId