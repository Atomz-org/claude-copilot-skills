{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *
  , {{ add_erp_fields(columns=['EmployeeId']) }}
from {{ ref('fortnox_bi_dim_employees_staging') }}