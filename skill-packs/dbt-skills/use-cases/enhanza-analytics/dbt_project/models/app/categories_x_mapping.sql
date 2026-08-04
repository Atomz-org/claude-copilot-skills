{{ config(
  alias=(model_alias(model.name)),
  enabled = any_source_enabled(['fortnox', 'tripletex', 'visma_eaccounting', 'visma_economic', 'xledger'])
) }}
{#-
  The enabled gate replicates dimension_mapping_dbt's verbatim, because the d0_dbt CTE
  below refs it unconditionally: this model cannot exist without it. It previously had no
  gate at all, so any run whose enablement disabled dimension_mapping_dbt — every combo
  without is_erp_enabled, and every erp run on a source outside its list — failed at parse
  with "depends on a node which is disabled". Found by the sample build, which parses with
  exactly one tenant's flags instead of refresh.sh's everything-on set.
-#}

{%- set org_enabled = any_source_enabled(['fortnox', 'seventime', 'tripletex', 'visma_eaccounting', 'visma_economic', 'upsales']) -%}

with d0_dbt as (
  select
    OrgId
    , DimensionId
    , CategoryId
  from {{ ref('dimension_mapping_dbt') }}
),

d0_user as (
  select
    cast(OrgId as string) OrgId
    , DimensionId
    , CategoryId
  from {{ source('app', 'dimension_mapping') }}
),

d0_combined as (
  select
    dbt.OrgId
    , dbt.DimensionId
    , dbt.CategoryId
  from d0_dbt dbt
  where not exists (
    select 1
    from d0_user ui
    where dbt.DimensionId = ui.DimensionId
      and dbt.OrgId = ui.OrgId
  )
  union all

  select
    usr.OrgId
    , usr.DimensionId
    , usr.CategoryId
  from d0_user usr
),

d0 as (
  --reworked view to host up to 3 hierarchy levels
  select  
    dm.OrgId
    , dm.DimensionId
    , case
      when instr(dm.DimensionId, '-ds_') = 0 --old ID
        and dc3.DimensionColumn <> 'AccountId' --Accounts have separate ID
        {% if org_enabled %}
          then dm.DimensionId || '-' || regexp_extract(OrgIdERP, r'-([^\\-]+)$')
        {% else %}
          then dm.DimensionId || '-ds_fortnox'
        {% endif %}
      else dm.DimensionId
    end DimensionIdERP
    , coalesce(dm.CategoryId, dc3.CategoryId, dc2.CategoryId, dc1.CategoryId) CategoryId
    , coalesce(dc3.ParentId, dc2.ParentId, dc1.ParentId) ParentId
    , coalesce(dc3.Name, dc2.Name, dc1.Name) Name
    , case
      when dc1.Name is null then 'Others'
      else coalesce(dc3.Name, 'Others') 
    end Level3
    , case
      when dc1.Name is null and dc2.Name is null then cast(null as string)
      when dc1.Name is null then dc3.CategoryId 
      else coalesce(dc2.CategoryId, dc3.CategoryId) 
    end Level2ID
    , case
      when dc1.Name is null and dc2.Name is null then 'Others'
      when dc1.Name is null then dc3.Name 
      else coalesce(dc2.Name, dc3.Name, 'Others') 
    end Level2
    , coalesce(dc1.CategoryId, dc2.CategoryId, dc3.CategoryId) Level1ID
    , coalesce(dc1.Name, dc2.Name, dc3.Name, 'Others') Level1
    , dc3.DimensionTable
    , dc3.DimensionColumn
    , row_number() over (partition by dm.DimensionId, dc3.DimensionTable order by dm.CategoryId) rn
  from {{ source('app', 'dimension_categories') }} dc3
  left join {{ source('app', 'dimension_categories') }} dc2
    on dc3.ParentId = dc2.CategoryId
  left join {{ source('app', 'dimension_categories') }} dc1
    on dc2.ParentId = dc1.CategoryId
  left join d0_combined dm
    on dm.CategoryId = dc3.CategoryId
  {% if org_enabled %}
    left join {{ ref('erp_bi_dim_company') }} org
      on org.OrgId = dm.OrgId
  {% endif %}
  where dc3.isActive is not false and dc2.isActive is not false and dc1.isActive is not false
)

--de-duplicate the data at DBT level!
select
  * except(rn)
from d0
where rn=1