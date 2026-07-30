{{ config(alias=(model_alias(model.name))) }}
with p as (
  select
    ProjectNumber
    , row_number() over(order by ProjectNumber asc) rn
  from {{ source('fortnox_api_demo', 'projects') }}
  where OrgId = (select min(OrgId) from {{ source('fortnox_api_demo', 'projects') }})
  group by 1
)
select 
  '1111111111' OrgId
  , cast(null as string) Comments
  , cast(null as string) ContactPerson
  , 'Project #' || rn * 100 Description
  , cast(null as date) EndDate
  , cast(null as string) ProjectLeader
  , cast(rn * 100 as string) ProjectNumber
  , 'ONGOING' Status
  , cast(null as date) StartDate
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO 
from p