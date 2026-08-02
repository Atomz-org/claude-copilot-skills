{{ config(materialized='ephemeral', enabled = var('is_upsales_enabled', false)) }}

with main as (
  select distinct
    OrgId
    , json_extract_scalar(client, '$.name') OrgName
    , json_extract_scalar(client, '$.state')  City
    , cast(id as string) UpsalesId
  from {{ source('upsales_api', 'self') }}
)
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main