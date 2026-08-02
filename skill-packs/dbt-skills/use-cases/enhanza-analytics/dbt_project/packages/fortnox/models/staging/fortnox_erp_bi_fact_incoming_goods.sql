{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *
  , voided as IsVoided
  , {{ add_erp_fields(columns=['OrgId', 'ArticleId']) }}
from {{ ref('fortnox_bi_fact_incoming_goods_staging') }}