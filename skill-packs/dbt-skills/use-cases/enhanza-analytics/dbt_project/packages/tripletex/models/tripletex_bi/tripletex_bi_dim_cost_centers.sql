{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  CostCenterId
  , Code
  , Description
  , IsActive
from {{ ref('tripletex_bi_dim_cost_centers_staging') }}