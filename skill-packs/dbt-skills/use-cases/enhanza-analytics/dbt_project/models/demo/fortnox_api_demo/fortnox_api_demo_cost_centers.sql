{{ config(alias=(model_alias(model.name))) }}
with cc as (
  select
    Code
    , row_number() over(order by Code asc) rn
  from {{ source('fortnox_api_demo', 'cost_centers') }}
  where OrgId = (select min(OrgId) from {{ source('fortnox_api_demo', 'cost_centers') }})
)
select 
  '1111111111' OrgId
  , cast(rn * 100 as string) Code
  , 'Cost center #' || rn * 100 Description
  , cast(null as string) Note
  , TRUE Active
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO 
from cc