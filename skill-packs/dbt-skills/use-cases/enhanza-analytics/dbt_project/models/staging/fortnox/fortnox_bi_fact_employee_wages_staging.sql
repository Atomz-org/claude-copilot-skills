{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select  
  parse_date('%Y-%m-%d', w.FirstDay) WageChangeDate
  , cast(w.MonthlySalary as float64) MonthlySalaryAtDate
  , cast(w.HourlyPay as float64) HourlyPayAtDate
  , e.OrgId || '-' || e.EmployeeId EmployeeId
  , e.OrgId
  , e.OrgId || '-' || {{blank_to_null('e.CostCenter')}} CostCenterId
  , e.OrgId || '-' || {{blank_to_null('e.Project')}} ProjectId
from {{ source('fortnox_api', 'employees') }} e
  , unnest(DatedWages) w
order by 4, 1 asc