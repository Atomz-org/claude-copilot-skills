{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}


with min_max as (
  select
    OrgId
    , date(date_trunc(min(createDate), year)) minDate
    , date(date_trunc(max(createDate), year)) maxDate
  from {{ source('seventime_api', 'invoices') }}
  group by OrgId
)
, define_dates as (
  select
    OrgId
    , MinDate + interval year_offset year FromDate
    , last_day(MinDate + interval year_offset year, year) ToDate
  from
    min_max
    , unnest(generate_array(0, date_diff(MaxDate, MinDate, year))) year_offset
)
, pre as (
  select
    case
      when current_date() between FromDate and ToDate then 0
      when current_date() > ToDate then -1
      else 1
    end multi
    , OrgId
    , OrgId || '-' || extract(year from FromDate) FinancialYearId
    , cast(extract(year from FromDate) as string) Id
    , date(FromDate) FromDate
    , date(ToDate) ToDate
    , format_timestamp("%y%m%d", FromDate) || "-" || format_timestamp("%y%m%d", ToDate) FinancialYear
  from define_dates
),
pre2 as (
  select
    row_number() over (partition by OrgId, multi order by FromDate desc) rn_past
    , row_number() over (partition by OrgId, multi order by FromDate asc)rn_future
    , *
  from
    pre
)
select
  cast(OrgId as string) as OrgId
  , FinancialYearId
  , cast(Id as STRING)  as Id
  , FromDate
  , ToDate
  , FinancialYear
  , case
    when multi = -1 then rn_past * multi
    when multi = 1 then rn_future
    else multi
  end FyCounter
  , {{ add_erp_fields(columns=['FinancialYearId']) }}
from
  pre2
order by
  OrgId,
  FyCounter desc