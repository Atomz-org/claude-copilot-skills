{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with main as (
  select
    OrgId
    , companyName OrgName
    , initcap(city) City
    , cast(id as string) SeventimeId
  from {{ source('seventime_api', 'companyinformation') }}
)
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main