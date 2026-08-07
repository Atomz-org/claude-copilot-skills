{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

-- Columns enumerated by scripts/expand_star_models.py from the upstream's own
-- declaration; `select *` gave this model no column contract. Regenerate after
-- changing the upstream contract; do not hand-edit the list.
select 
    Name
    , Date
    , ResponsiblePerson
    , Status
    , IsUsingStockPoints
    , StockTakenQuantity
    , TotalQuantityInStock
    , OrgId
    , StockTakingId
    , ArticleId
    , StockPointId
    , CostCenterId
    , ProjectId,
{{ add_erp_fields(columns=['OrgId', 'ArticleId', 'StockTakingId', 'StockPointId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_stocktakings_staging') }}