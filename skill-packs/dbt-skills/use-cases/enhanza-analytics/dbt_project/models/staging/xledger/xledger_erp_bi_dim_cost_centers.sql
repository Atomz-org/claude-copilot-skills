{{ config(materialized='ephemeral', enabled = var('is_xledger_enabled', false)) }}

with main as (

select
    OrgId || '-' || id CostCenterId
    , code Code
    , description Description
    , CASE 
        WHEN dateTo IS NULL OR dateTo >= CURRENT_DATE() 
        THEN TRUE
        ELSE FALSE
      END AS isActive
    , coalesce(text1, text2) Note
from
  {{ source('xledger_api', 'object_values') }}
where objectKindDbId=30 --costcenters
)
select *
  , {{ add_erp_fields(columns=['CostCenterId']) }}
from main