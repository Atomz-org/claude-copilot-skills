{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from {{ ref('fortnox_bi_dim_company_staging') }}