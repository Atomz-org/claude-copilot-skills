{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *,
{{ add_erp_fields(columns=['OrgId', 'ArticleId', 'StockPointId']) }}
from {{ ref('fortnox_bi_fact_stockbalance_staging') }}