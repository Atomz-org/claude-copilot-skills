{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *,
{{ add_erp_fields(columns=['OrgId', 'EmployeeId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_salary_transactions_staging') }}
