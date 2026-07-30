{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  ItemId,
  AvailableStock,
  InStock,
  StockPointCode,
  OrgId,
  OrgId || '-' || {{ blank_to_null('ItemId') }} as ArticleId,
  OrgId || '-' || {{ blank_to_null('StockPointCode') }} as StockPointId,
  date(ENZ_SYNC_TS) Date
from
  {{ source('fortnox_api', 'stockbalance') }}
where 
  ifnull(enz_sync_ts, enz_created_at) 
    in (select max(ifnull(enz_sync_ts, enz_created_at)) from {{ source('fortnox_api', 'stockbalance') }})
