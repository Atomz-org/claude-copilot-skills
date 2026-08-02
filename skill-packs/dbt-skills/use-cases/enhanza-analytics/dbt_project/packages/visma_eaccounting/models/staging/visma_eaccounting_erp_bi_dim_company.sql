{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with main as (
  select
    OrgId as OrgId,
    Name as OrgName,
    initcap(City) as City,
    cast(CompanyIdentifier as string) as VismaId
  from
    {{ source('visma_eaccounting_api', 'companysettings') }}
)
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main