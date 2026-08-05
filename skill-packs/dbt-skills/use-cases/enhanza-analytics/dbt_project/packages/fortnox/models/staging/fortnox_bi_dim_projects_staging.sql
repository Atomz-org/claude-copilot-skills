{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with p as (
select
  OrgId || '-' || {{ blank_to_null('ProjectNumber') }} as ProjectId,
  ProjectNumber,
  Description,
  Startdate,
  EndDate,
  Comments,
  ContactPerson,
  ProjectLeader,
  initcap(Status) as Status,
  row_number() over (partition by OrgId, lower(ProjectNumber) order by Startdate desc) as rn
from
  {{ source('fortnox_api', 'projects') }}
)
select ProjectId, ProjectNumber, Description, Startdate, EndDate, Comments, ContactPerson, ProjectLeader, Status
from p
where rn = 1
