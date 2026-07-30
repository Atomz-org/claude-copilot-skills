{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || {{ blank_to_null('Code') }} as PriceListId,
  Description,
  {{ blank_to_null('Comments') }} as Comments,
  Preselected
from
  {{ source('fortnox_api', 'pricelists') }}