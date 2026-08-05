{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *,
{{ add_erp_fields(columns=['OrgId', 'ArticleId']) }}
from {{ ref('fortnox_bi_fact_purchase_orders_staging') }}