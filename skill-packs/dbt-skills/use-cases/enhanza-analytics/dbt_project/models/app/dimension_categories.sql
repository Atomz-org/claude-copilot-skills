{{ config(
  enabled = any_source_enabled(['fortnox', 'tripletex', 'visma_eaccounting', 'visma_economic', 'xledger'])
  , materialized='incremental'
  , incremental_strategy='merge'
  , unique_key=['DimensionTable', 'DimensionColumn', 'CategoryId']
  , full_refresh=false
  , alias=(model_alias(model.name))
) }}

select
  Name
  , isActive
  , DimensionTable
  , DimensionColumn
  , CategoryId
  , ParentId
  , cast(null as string) as SectionId
  , cast(null as string) as VersionId
from (
  select distinct
    Name1 Name
    , TRUE isActive
    , 'chart_of_accounts' DimensionTable
    , 'AccountId' DimensionColumn
    , ID1 CategoryId
    , cast(null as string) ParentId
  from {{ source('global_ds_chart_of_accounts', 'full_mapping') }}
    union all
  select distinct
    Name2
    , TRUE
    , 'chart_of_accounts'
    , 'AccountId'
    , ID2
    , ID1
  from {{ source('global_ds_chart_of_accounts', 'full_mapping') }}
    union all
  select distinct
    Name3
    , TRUE
    , 'chart_of_accounts'
    , 'AccountId'
    , ID3
    , ID2
  from {{ source('global_ds_chart_of_accounts', 'full_mapping') }}
)