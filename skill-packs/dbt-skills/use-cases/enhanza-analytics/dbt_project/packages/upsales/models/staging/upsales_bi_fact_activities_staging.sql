{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name) ) }}

select
  OrgId
  , OrgId || '-' || id ActivityId
  , parse_date('%F', left(`date`, 10)) ActivityDate
  , date(regDate) RegistrationDate
  , date(closeDate) CloseDate
  , {{ blank_to_null("json_extract_scalar(activityType, '$.name')") }} ActivityType
  , `priority` PriorityLevel
  , json_extract_scalar(lastOutcome, '$.outcome') Outcome
  , {{ blank_to_null('description') }} `Description`
  , {{ blank_to_null('notes') }} Notes
  , json_extract_scalar(projectPlan, '$.name') ProjectPlan
  , json_extract_scalar(regBy, '$.name') RegisteredByUser
  , OrgId || '-' || json_extract_scalar(client, '$.id') CustomerId
  , OrgId || '-' || json_extract_scalar(project, '$.id') ProjectId
  , OrgId || '-' || parentActivityId ParentActivityId
  , OrgId || '-' || parentAppointmentId ParentAppointmentId
  , OrgId || '-' || json_extract_scalar(opportunity, '$.id') OpportunityId
  , OrgId || '-' || extract(year from parse_date('%F', left(`date`, 10))) FinancialYearId
from {{ source('upsales_api', 'activities') }} 
where isAppointment = 0