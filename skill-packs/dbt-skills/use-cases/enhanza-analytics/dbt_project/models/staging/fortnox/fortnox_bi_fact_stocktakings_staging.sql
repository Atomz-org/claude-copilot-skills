{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  s.Name
  , date(s.date) Date
  , s.responsible ResponsiblePerson
  , s.state Status
  , s.usingStockPoints IsUsingStockPoints
  , cast(json_extract_scalar(r, '$.stockTakenQuantity') as float64) StockTakenQuantity
  , cast(json_extract_scalar(r, '$.totalQuantityInStock') as float64) TotalQuantityInStock
  , s.OrgId
  , s.OrgId || '-' || {{ blank_to_null('s.id') }} StockTakingId 
  , s.OrgId || '-' || {{ blank_to_null('json_extract_scalar(r, "$.itemId")') }} ArticleId
  , s.OrgId || '-' || {{ blank_to_null('p.Code') }} StockPointId
  , s.OrgId || '-' || {{ blank_to_null('s.costCenterCode') }} CostCenterId
  , s.OrgId || '-' || {{ blank_to_null('s.projectId') }} ProjectId
from {{ source('fortnox_api', 'stocktakings') }} s
, unnest(cast(json_extract_array(s.Rows) as array<JSON>)) r
left join {{ source('fortnox_api', 'stockpoints') }} p
  on p.Id=json_extract_scalar(r, '$.stockPointId')
  and p.OrgId=s.OrgId