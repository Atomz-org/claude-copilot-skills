{{ config(materialized='ephemeral', enabled = var('is_tripletex_enabled', false)) }}

with main as (
  select
    d.name OrgName
    , d.OrgId
    , m.name City
    , d.id TripletexId
    , row_number() over (
        partition by d.OrgId
        order by case when d.endDate is null then 0 else 1 end, d.endDate desc
      ) as rn
  from {{ source('tripletex_api', 'division') }} d
  left join {{ source('tripletex_api', 'municipality') }} m
    on json_extract_scalar(d.municipality, '$.id') = cast(m.id as string)
    and m.OrgId = d.OrgId
)
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main
where rn = 1