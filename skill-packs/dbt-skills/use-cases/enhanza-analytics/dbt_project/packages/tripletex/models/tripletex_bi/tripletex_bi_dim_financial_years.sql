{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId
  , FinancialYearId
  , Id
  , FromDate
  , ToDate
  , FinancialYear
  , FyCounter
from {{ ref('tripletex_bi_dim_financial_years_staging') }}