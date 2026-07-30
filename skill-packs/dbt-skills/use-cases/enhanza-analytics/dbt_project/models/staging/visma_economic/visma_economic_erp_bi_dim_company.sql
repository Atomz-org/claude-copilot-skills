{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with main as (
-- dummy data to make logic_bi views available
  select
    OrgId
    , json_extract_scalar(company, '$.name') OrgName
    , initcap(json_extract_scalar(company, '$.city')) City
    , cast(agreementNumber as string) VismaId
  from {{ source('visma_economic_api', 'self') }}
)
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main