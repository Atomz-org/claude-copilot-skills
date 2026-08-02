{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name) ) }}

select
  OrgId
  , OrgId || '-' || id AppointmentId
  , date(`date`) AppointmentDate
  , date(regDate) RegistrationDate
  , date(endDate) EndDate
  , {{ blank_to_null("json_extract_scalar(activityType, '$.name')") }} AppointmentType
  , {{ blank_to_null('outcome') }} `Status`
  , {{ blank_to_null('location') }} `Location`
  , `private` isPrivate
  , isExternalHost
  , {{ blank_to_null('description') }} `Description`
  , {{ blank_to_null('notes') }} Notes
  , json_extract_scalar(regBy, '$.name') RegisteredByUser
  , json_extract_scalar(projectPlan, '$.name') ProjectPlan
  , weblinkUrl WebLink
  , OrgId || '-' || json_extract_scalar(client, '$.id') CustomerId
  , OrgId || '-' || json_extract_scalar(project, '$.id') ProjectId
  , OrgId || '-' || json_extract_scalar(opportunity, '$.id') OpportunityId
  , OrgId || '-' || extract(year from date) FinancialYearId
from {{ source('upsales_api', 'appointments') }}  
where isAppointment = 1