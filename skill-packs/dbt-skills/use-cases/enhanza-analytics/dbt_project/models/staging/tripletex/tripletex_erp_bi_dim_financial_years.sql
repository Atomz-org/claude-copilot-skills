{{ config(materialized='ephemeral', enabled = var('is_tripletex_enabled', false)) }}

with today as (
  select
    max(Date) Today
  from {{ source('public', 'calendar') }}
),

pre_calc as (
  select
    OrgId
    , OrgId || '-' || id FinancialYearId
    , id
    , `start`
    , `end`
    , today.Today
  from {{ source('tripletex_api', 'annual_account') }}
  , today
)

select
  cast(OrgId as string) as OrgId
  , FinancialYearId
  , cast(id as String) Id
  , date(`start`) FromDate
  -- in Tripletex, dates are from yyyy-01-01 to yyyy-01-01 which makes 1st January ambiguous
  , case
      when extract(day from `start`) <> extract(day from `end`) then date(`end`)
      else date_sub(`end`, INTERVAL 1 day)
    end ToDate
  , format_date('%y%m%d', date(`start`)) || '-' ||
    case
      when extract(day from `start`) <> extract(day from `end`) then format_date('%y%m%d', date(`end`))
      else format_date('%y%m%d', date_sub(`end`, INTERVAL 1 day))
  end FinancialYear
  , date_diff(`start`, Today, year) FyCounter

, {{ add_erp_fields(columns=['FinancialYearId']) }}
from pre_calc