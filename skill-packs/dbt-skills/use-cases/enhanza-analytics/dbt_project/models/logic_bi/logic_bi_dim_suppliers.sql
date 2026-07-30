{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'visma_economic', 'tripletex'])
) }}

{% set cxm_cols = ['SupplierId', 'City'] %}

select
  SupplierIdERP || '-S' SupplierId
  , d0.Name || ' (' || SupplierNumber || ')' SupplierName
  , City SupplierCity
  , Country SupplierCountry
  , d0.DataSource
  , d0.isActive
  {{ cxm_select(cxm_cols) }}
from {{ ref('erp_bi_dim_suppliers') }} d0
{{ cxm_left_join(model_alias("dim_suppliers"), cxm_cols) }}
order by 1