{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId as OrgId,
  Name as OrgName,
  initcap(City) as City,
  DatabaseNumber as FortnoxId
from
  {{ source('fortnox_api', 'company_settings') }}