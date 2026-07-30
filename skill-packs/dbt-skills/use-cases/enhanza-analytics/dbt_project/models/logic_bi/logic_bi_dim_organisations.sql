{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'seventime', 'tripletex', 'upsales', 'visma_eaccounting', 'visma_economic'])
) }}

select
  OrgIdERP OrgId
  , OrgId OrganisationNumber
  , OrgName OrganisationName
  , DataSource
from {{ ref('erp_bi_dim_company') }}
order by 1