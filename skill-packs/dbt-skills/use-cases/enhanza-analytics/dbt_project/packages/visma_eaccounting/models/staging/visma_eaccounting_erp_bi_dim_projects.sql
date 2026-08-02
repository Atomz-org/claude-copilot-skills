{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with p as (
  select
    OrgId || '-' || Id ProjectId
    , Number ProjectNumber
    , Name Description
    , Startdate
    , EndDate
    , Notes Comments
    --ContactPersonProjectLeader and Status are not available
    , row_number() over (partition by OrgId, lower(Number) order by Startdate desc) as rn
  from
    {{ source('visma_eaccounting_api', 'projects') }}
)
, final as (
  select
    ProjectId
    , ProjectNumber
    , Description
    , Startdate
    , EndDate
    , Comments
    , cast(null as STRING) as ContactPerson
    , cast(null as STRING) as ProjectLeader
    , cast(null as STRING) as Status
  from p
  where rn = 1
)
select *
  , {{ add_erp_fields(columns=['ProjectId']) }}
from final
