{{ config(
    alias=(model_alias(model.name)),
        enabled = any_source_enabled(['fortnox', 'visma_eaccounting', 'xledger', 'tripletex'])
) }}

{% set cxm_cols = ['CostCenterId'] %}

select
    CostCenterIdERP CostCenterId
    , Description || ' (' || Code || ')' CostCenter
    , Code CostCenterNumber
    , d0.DataSource
    , d0.IsActive as isActive
    {{ cxm_select(cxm_cols) }}
from {{ ref('erp_bi_dim_cost_centers') }} d0
{{ cxm_left_join(model_alias("dim_cost_centers"), cxm_cols) }}
order by 1