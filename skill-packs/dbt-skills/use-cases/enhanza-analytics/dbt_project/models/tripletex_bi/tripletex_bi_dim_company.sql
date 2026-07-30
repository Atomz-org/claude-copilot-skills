{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgName
  , OrgId
  , City
  , TripletexId
from {{ ref('tripletex_bi_dim_company_staging') }}