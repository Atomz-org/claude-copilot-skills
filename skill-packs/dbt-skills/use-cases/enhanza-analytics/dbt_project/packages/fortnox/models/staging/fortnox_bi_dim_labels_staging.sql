{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || Id as LableId,
  Description
from
  {{ source('fortnox_api', 'labels') }}