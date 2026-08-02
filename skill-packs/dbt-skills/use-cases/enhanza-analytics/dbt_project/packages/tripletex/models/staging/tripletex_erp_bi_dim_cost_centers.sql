{{ config(materialized='ephemeral', enabled = var('is_tripletex_enabled', false)) }}

with main as (
  select
    OrgId || '-' || id CostCenterId
    , case
      when instr(`name`, ' ') = 0 then cast(id as string)
      else split(`name`, ' ')[offset(0)]
    end Code
    , case
      when instr(`name`, ' ') = 0 then `name`
      else trim(array_to_string(array(select word from unnest(split(`name`, ' ')) word with offset where offset > 0), ' '))
    end Description
    , not isInactive IsActive
    , cast(null as STRING) as Note
from {{ source('tripletex_api', 'department') }}
)
select *
  , {{ add_erp_fields(columns=['CostCenterId']) }}
from main