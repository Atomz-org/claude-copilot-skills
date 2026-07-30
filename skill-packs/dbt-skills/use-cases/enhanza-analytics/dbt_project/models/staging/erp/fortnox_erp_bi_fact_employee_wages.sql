{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  WageChangeDate
  , MonthlySalaryAtDate
  , HourlyPayAtDate
  , EmployeeId
  , OrgId
  , CostCenterId
  , ProjectId
  , {{ add_erp_fields(columns=['EmployeeId', 'OrgId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_employee_wages_staging') }}
