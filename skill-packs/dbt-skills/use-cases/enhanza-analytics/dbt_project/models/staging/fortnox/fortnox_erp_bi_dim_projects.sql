{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  ProjectId
  , ProjectNumber
  , Description
  , Startdate
  , EndDate
  , Comments
  , ContactPerson
  , ProjectLeader
  , Status
  , {{ add_erp_fields(columns=['ProjectId']) }}
from {{ ref('fortnox_bi_dim_projects_staging') }}