{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || itemId ArticleId
  , OrgId || '-' || supplierNumber SupplierId
  , trim(supplierItemId) SupplierArticleNo
  , trim(supplierItemName) SupplierArticleDescription
  , minimumQuantityToPurchase MinQtyToPurchase
  , currencyCode Currency
  , price Price
  , deliveryTime DeliveryTime
from {{ source('fortnox_api', 'itemsuppliers') }}