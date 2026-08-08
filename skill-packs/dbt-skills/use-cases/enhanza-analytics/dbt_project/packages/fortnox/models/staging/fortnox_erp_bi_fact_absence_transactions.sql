{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

-- Columns enumerated by scripts/expand_star_models.py from the upstream's own
-- declaration; `select *` gave this model no column contract. Regenerate after
-- changing the upstream contract; do not hand-edit the list.
select 
    Date
    , Extent
    , Hours
    , isHolidayEntitling
    , CauseCode
    , CauseCodeName
    , OrgId
    , EmployeeId
    , CostCenterId
    , ProjectId,
{{ add_erp_fields(columns=['OrgId', 'EmployeeId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_absence_transactions_staging') }}
