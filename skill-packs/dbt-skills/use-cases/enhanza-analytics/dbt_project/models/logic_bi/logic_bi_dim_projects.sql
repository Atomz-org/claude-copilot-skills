{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'tripletex', 'visma_eaccounting', 'xledger'])
) }}

{% set employee_enabled = model_is_provided('dim_employees')%}
{% set cxm_cols = ['ProjectId'] %}

select
  d0.ProjectIdERP ProjectId
  , Description || ' (' || ProjectNumber || ')' Project
  , ProjectNumber
  , ProjectLeader as ProjectManager
  , cxm.Level1 ProjectManagerGroup
  , cxm.level2 ProjectManagerSubGroup
  , cxm.level3 ProjectManagerSubSubGroup
  , cxm.Level1ID ProjectManagerGroupId
  , cxm.level2ID ProjectManagerSubGroupId
  , cxm.CategoryId ProjectManagerSubSubGroupId
  , d0.DataSource
  {{ cxm_select(cxm_cols) }}
from {{ ref('erp_bi_dim_projects') }} d0
left join {{ ref('categories_x_mapping') }} cxm
  on cxm.DimensionIdERP = split(d0.ProjectId, '-')[offset(0)] || '-' || regexp_extract(d0.ProjectId, r'^(?:[^-]*-){2}(.*)')  || '|' || d0.ProjectLeader
  and cxm.DimensionTable='dim_employees'
  and cxm.DimensionColumn='EmployeeId'
{{ cxm_left_join(model_alias("dim_projects"), cxm_cols) }}
order by 1