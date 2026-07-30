{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  v.OrgId
  , c.OrgName
  , fy.FinancialYear
  , fy.FyCounter
  , v.TransactionDate
  , v.Description VoucherDescription
  , v.TransactionInformation
  , v.VoucherSeries
  , v.VoucherNumber
  , vs.Description VoucherSeriesName
  , v.Account
  , a.AccountName
  , a.AccountClassId
  , case
    when cast(v.Account as integer) between 1000 and 1999 then "1. Tillgångar" --1. Assets
    when cast(v.Account as integer) between 2000 and 2999 then "2. Eget kapital och skulder" --2. Equity and Liabilities
    when cast(v.Account as integer) between 3000 and 3999 then "3. Intäkter" --3. Operating income/revenue
    when cast(v.Account as integer) between 4000 and 4999 then "4. Materialkostnader" --4. Cost of goods
    when cast(v.Account as integer) between 5000 and 6999 then "5-6. Övriga kostnader" --5-6. Other external costs
    when cast(v.Account as integer) between 7000 and 7999 then "7. Personal, avskrivningar m.m." --7. Personnel costs
    when cast(v.Account as integer) between 8000 and 8999 then "8. Finansiella intäkter/kostnader" --8. Financials
    else cast(v.Account as string)
  end AccountClass
  , a.MainAccountId
  , a.MainAccount
  , a.SubAccountId
  , a.SubAccount
  , cc.Code CostCenterId
  , cc.Description CostCenter
  , p.ProjectNumber ProjectId
  , p.Description Project
  , v.Balance
  , v.ReferenceType
  , v.ReferenceNumber
  , coalesce(cust.Name, s.Name) ReferenceName
from {{ ref('fortnox_bi_fact_vouchers_staging') }} v
left join {{ ref('fortnox_bi_dim_company_staging') }} c
  on v.OrgId = c.OrgId
left join {{ ref('fortnox_bi_dim_financial_years_staging') }} fy
  on v.FinancialYearId = fy.FinancialYearId
left join {{ ref('fortnox_bi_dim_voucher_series_staging') }} vs
  on v.VoucherSeriesId = vs.VoucherSeriesId
left join {{ ref('fortnox_bi_dim_accounts_staging') }} a
  on v.AccountId = a.AccountId
left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc
  on v.CostCenterId = cc.CostCenterId
left join {{ ref('fortnox_bi_dim_projects_staging') }} p
  on v.ProjectId = p.ProjectId
left join {{ ref('fortnox_bi_dim_customers_staging') }} cust
  on v.CustomerId = cust.CustomerId
left join {{ ref('fortnox_bi_dim_suppliers_staging') }} s
  on v.SupplierId = s.SupplierId