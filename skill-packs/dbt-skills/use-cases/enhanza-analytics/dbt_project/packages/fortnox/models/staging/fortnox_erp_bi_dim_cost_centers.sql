{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  CostCenterId
  , Code
  , Description
  , IsActive
  , Note
  , {{ add_erp_fields(columns=['CostCenterId']) }}
from {{ ref('fortnox_bi_dim_cost_centers_staging') }}

