{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


with e as (
  select  
    e.OrgId || '-' || e.EmployeeId EmployeeId
    , e.EmployeeId EmployeeNumber
    , e.FullName EmployeeName
    , date(e.EmploymentDate) HiringDate
    , date(e.EmployedTo) FiringDate
    , e.EmploymentForm
    , e.SalaryForm
    , if(e.JobTitle='', null, e.JobTitle) JobTitle
    , e.PersonelType
    , cast(e.MonthlySalary as float64) CurrentMonthlySalary
    , cast(e.HourlyPay as float64) CurrentHourlyPay
    , PersonalIdentityNumber
    , e.Address1 Address
    , if(replace(e.PostCode, ' ', '')='' or replace(e.PostCode, ' ', '')='-', null, replace(e.PostCode, ' ', '')) ZipCode
    , initcap(e.City) City
    , replace(initcap( if(e.Country = "", null, e.Country) ), 'Sverige', 'Sweden') Country
    , coalesce(if(e.Phone1='', null, e.Phone1), if(e.Phone2='', null, e.Phone2)) Phone
    , e.Email
    , e.ForaType
    , e.TaxAllowance
    , e.TaxTable
    , e.TaxColumn
    , e.AutoNonRecurringTax isAutoNonRecurringTax
    , e.NonRecurringTax
    , e.ClearingNo
    , not e.Inactive as isActive
    , e.BankAccountNo
    , e.OrgId || '-' || {{blank_to_null('e.CostCenter')}} CostCenterId
    , e.OrgId || '-' || {{blank_to_null('e.Project')}} ProjectId
  from {{ source('fortnox_api', 'employees') }} e
)

, sch as (
  select 
    json_value(sch, '$.ScheduleId') CurrentScheduleCode
    , e.OrgId || '-' || e.EmployeeId EmployeeId
    , row_number() over (
    partition by e.OrgId || '-' || e.EmployeeId
    order by 
        case 
        when date(json_value(sch, '$.Date')) <= current_date() then date(json_value(sch, '$.Date')) 
        else null
        end desc
    ) row_num
    , date(json_value(sch, '$.Date')) ScheduleChangeDate
    , safe_cast(json_value(sch, '$.Hours') as float64) CurrentScheduledHours
    , safe_cast(json_value(sch, '$.IWH1') as float64) IWH1
    , safe_cast(json_value(sch, '$.IWH2') as float64) IWH2
    , safe_cast(json_value(sch, '$.IWH3') as float64) IWH3
    , safe_cast(json_value(sch, '$.IWH4') as float64) IWH4
    , safe_cast(json_value(sch, '$.IWH5') as float64) IWH5
  from {{ source('fortnox_api', 'employees') }} e
    , unnest(json_extract_array(e.DatedSchedulesExtended)) sch
)

select 
  e.*
  , sch.* except(EmployeeId, row_num, ScheduleChangeDate)
from e
left join sch 
  on e.EmployeeId = sch.EmployeeId
  and sch.ScheduleChangeDate <= current_date()
  and sch.row_num = 1