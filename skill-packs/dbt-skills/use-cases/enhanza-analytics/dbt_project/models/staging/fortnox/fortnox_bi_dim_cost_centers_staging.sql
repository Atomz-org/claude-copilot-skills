{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || {{ blank_to_null('Code') }} as CostCenterId,
  Code,
  Description,
  Active as IsActive,
  Note
from
  {{ source('fortnox_api', 'cost_centers') }}