{{ config(alias='fortnox_bi_fact_incominggoods', enabled = source_is_enabled(model.name)) }}

select
  i.OrgId,
  i.id,
  i.date,
  r.itemId as ArticleNumber,
  r.itemUnit,
  r.directCost,
  -- Only null value exists. Currency?
  r.orderedQuantity,
  r.remainingOrderedQuantity,
  r.receivedQuantity,
  r.backOrderQuantity,
  r.takenQuantity,
  r.invoicedQuantity,
  r.isStockItem,
  r.batch,
  i.released,
  i.completed,
  i.voided,
  i.note,
  i.OrgId || '-' || r.purchaseOrderId as purchaseOrderId,
  i.OrgId || '-' || {{ blank_to_null('r.itemId') }} as ArticleId,
  i.OrgId || '-' || {{ blank_to_null('i.supplierNumber') }} as SupplierId,
  i.OrgId || '-' || {{ blank_to_null('i.stockPointCode') }} as stockPointId,
  i.OrgId || '-' || {{ blank_to_null('r.projectId') }} as ProjectId,
  i.OrgId || '-' || {{ blank_to_null('r.costCenterCode') }} as CostCenterId,
from
  {{ source('fortnox_api', 'incominggoods') }} i
  cross join UNNEST(i.rows) r