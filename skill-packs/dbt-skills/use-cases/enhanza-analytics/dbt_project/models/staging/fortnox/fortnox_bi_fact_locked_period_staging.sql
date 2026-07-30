{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
    OrgId
    , date(EndDate) LockedPeriodDate
from {{ source('fortnox_api', 'lockedperiod') }}