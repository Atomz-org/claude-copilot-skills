{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select 
  Date
  , Hours
  , CauseCode
  , cc.Description CauseCodeName
  , a.OrgId
  , a.OrgId || '-' || a.EmployeeId EmployeeId
  , a.OrgId || '-' || coalesce({{blank_to_null('a.CostCenter')}}, {{blank_to_null('e.CostCenter')}}) CostCenterId
  , a.OrgId || '-' || coalesce({{blank_to_null('a.Project')}}, {{blank_to_null('e.Project')}}) ProjectId
from {{ source('fortnox_api', 'attendance_transactions') }} a
left join {{ source('public', 'cause_codes') }} cc
  on cc.Code=a.CauseCode
left join {{ source('fortnox_api', 'employees') }} e
  on e.OrgId = a.OrgId
  and e.EmployeeId = a.EmployeeId
