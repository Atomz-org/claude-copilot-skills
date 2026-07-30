{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


with d0 as (
    select 
        e.OrgId || '-' || json_value(sch, '$.ScheduleId') ScheduleId
        , json_value(sch, '$.ScheduleId') ScheduleCode
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
        , safe_cast(json_value(sch, '$.Hours') as float64) ScheduledHours
        , safe_cast(json_value(sch, '$.IWH1') as float64) IWH1
        , safe_cast(json_value(sch, '$.IWH2') as float64) IWH2
        , safe_cast(json_value(sch, '$.IWH3') as float64) IWH3
        , safe_cast(json_value(sch, '$.IWH4') as float64) IWH4
        , safe_cast(json_value(sch, '$.IWH5') as float64) IWH5
        , e.OrgId
        , e.OrgId || '-' || {{blank_to_null('e.CostCenter')}} CostCenterId
        , e.OrgId || '-' || {{blank_to_null('e.Project')}} ProjectId
    from {{ source('fortnox_api', 'employees') }} e
        , unnest(json_extract_array(e.DatedSchedulesExtended)) sch
)

select 
    ScheduleId
    , ScheduleCode
    , EmployeeId
    , if(row_num = 1 and ScheduleChangeDate <= current_date(), TRUE, FALSE) isCurrentSchedule
    , ScheduleChangeDate
    , ScheduledHours
    , IWH1
    , IWH2
    , IWH3
    , IWH4
    , IWH5
    , OrgId
    , CostCenterId
    , ProjectId
from d0
