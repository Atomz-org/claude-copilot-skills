{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with main as (
select
  cc.OrgId || '-' || json_extract_scalar(r, '$.Id') CostCenterId
  , json_extract_scalar(r, '$.ShortName') Code
  , json_extract_scalar(r, '$.Name') Description
  , IsActive
  , cast(null as STRING) as Note
from
  {{ source('visma_eaccounting_api', 'costcenters') }} cc
  , UNNEST(CAST(JSON_EXTRACT_ARRAY(cc.Items) AS ARRAY<JSON>)) r
)
select *
  , {{ add_erp_fields(columns=['CostCenterId']) }}
from main