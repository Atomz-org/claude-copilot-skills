{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  d.name OrgName
  , d.OrgId
  , m.name City
  , d.id TripletexId
from {{ source('tripletex_api', 'division') }} d
left join {{ source('tripletex_api', 'municipality') }} m
  on json_extract_scalar(d.municipality, '$.id') = cast(m.id as string)
  and m.OrgId = d.OrgId