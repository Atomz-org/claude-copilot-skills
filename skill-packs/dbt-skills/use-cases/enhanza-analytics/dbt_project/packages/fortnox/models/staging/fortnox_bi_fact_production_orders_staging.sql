{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with stockpoints as (
  select
    OrgId
    , Id
    , OrgId || '-' || {{ blank_to_null('Code') }} StockPointId
  from {{ source('fortnox_api', 'stockpoints') }}
)

select  
  po.id ProductionOrderNo
  , date(productionDate) ProductionDate
  , date(startDate) StartDate
  , date(EndDate) PlannedEndDate
  , initcap(productionState) ProductionStatus
  , cast(json_extract_scalar(r, '$.totalQuantityRequired') as float64) RequiredQuantity
  , note Description
  , po.OrgId
  , po.OrgId || '-' || po.id ProductionOrderId
  , po.OrgId || '-' || json_extract_scalar(r, '$.itemId') ArticleId
  , po.OrgId || '-' || {{ blank_to_null('costCenterCode') }} CostCenterId
  , po.OrgId || '-' || {{ blank_to_null('projectId') }} ProjectId
  , sp.StockPointId
from {{ source('fortnox_api', 'production_orders') }} po
, unnest(cast(json_extract_array(po.packageItems) as array<JSON>)) r
left join stockpoints sp
  on sp.OrgId = po.OrgId
  and sp.Id = po.inboundStockPointId
where po.documentState is null or po.documentState = 'completed'