{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *,
{{ add_erp_fields(columns=['OrgId', 'ArticleId', 'StockTakingId', 'StockPointId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_stocktakings_staging') }}