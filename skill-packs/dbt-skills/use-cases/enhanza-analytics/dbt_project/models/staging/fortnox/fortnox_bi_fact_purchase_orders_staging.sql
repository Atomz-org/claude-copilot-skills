{{ config(alias=('fact_purchaseorders'), enabled = source_is_enabled(model.name)) }}

select
  p.OrgId,
  p.id,
  p.orderDate,
  p.deliveryDate,
  p.purchaseType,
  p.ourReference,
  p.yourReference,
  p.responseState,
  p.purchaseOrderState,
  p.messageToSupplier,
  p.note,
  p.manuallyCompleted isManuallyCompleted,
  r.itemId as ArticleNumber,
  r.orderedQuantity,
  r.itemUnit,
  r.price as price,
  r.orderedQuantity * r.price as orderRowValue,
  r.currencyCode as Currency,
  p.currencyRate,
  r.orderedQuantity * r.price * p.currencyRate as orderRowValueSek,
  r.remainingOrderedQuantity,
  r.receivedQuantity,
  r.backOrderQuantity,
  r.isStockItem,
  p.OrgId || '-' || {{ blank_to_null('p.CustomerNumber') }} as CustomerId,
  p.OrgId || '-' || {{ blank_to_null('r.itemId') }} as ArticleId,
  p.OrgId || '-' || {{ blank_to_null('p.supplierNumber') }} as SupplierId,
  p.OrgId || '-' || {{ blank_to_null('p.stockPointCode') }} as stockPointId,
  p.OrgId || '-' || {{ blank_to_null('r.projectId') }} as ProjectId,
  p.OrgId || '-' || {{ blank_to_null('r.costCenterCode') }} as CostCenterId,
  p.OrgId || '-' || p.Id as purchaseOrderId
from
  {{ source('fortnox_api', 'purchaseorders') }} p
  cross join UNNEST(p.rows) r
