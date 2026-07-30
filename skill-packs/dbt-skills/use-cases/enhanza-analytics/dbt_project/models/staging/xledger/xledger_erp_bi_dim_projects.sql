{{ config(materialized='ephemeral', enabled = var('is_xledger_enabled', false)) }}

with main as (
  select
      OrgId || '-' || id ProjectId
      , code ProjectNumber
      , description Description
      , date(dateFrom) Startdate
      , date(dateTo) EndDate
      , coalesce(text1, text2) Comments
      --ContactPerson, ProjectLeader, Status not available
  from
    {{ source('xledger_api', 'object_values') }}
  where objectKindDbId=31 --projects
)
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
  , {{ add_erp_fields(columns=['ProjectId']) }}
from main