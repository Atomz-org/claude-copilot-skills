{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  OrgId
  , FinancialYearId
  , cast(Id as STRING)  as Id
  , FromDate
  , ToDate
  , FinancialYear
  , FyCounter
, {{ add_erp_fields(columns=['FinancialYearId']) }}
from {{ ref('fortnox_bi_dim_financial_years_staging') }}