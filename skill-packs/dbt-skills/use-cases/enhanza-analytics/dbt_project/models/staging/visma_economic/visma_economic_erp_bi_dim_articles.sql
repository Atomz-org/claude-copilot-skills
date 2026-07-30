{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with main as (
  select
    OrgId || '-' || if(productNumber = "", null, productNumber) ArticleId
    , productNumber ArticleNumber
    , ifnull(name, "[unknown]") Description
    --Manufacturer, ManufacturerArticleNumber, EAN, Active not available
    , cast(costPrice as float64) PurchasePrice
    , cast(json_extract_scalar(inventory, '$.inStock') as float64) QuantityInStock
    , cast(json_extract_scalar(inventory, '$.orderedByCustomers') as float64) ReservedQuantity
    , cast(salesPrice as float64) SalesPrice
    --StockGoods, StockPlace not available
    , cast(json_extract_scalar(inventory, '$.inStock') as float64) * cast(salesPrice as float64) StockValue
    --StockWarning, SupplierName, SupplierNumber not available
    , json_extract_scalar(productGroup, '$.name') Type
    , json_extract_scalar(unit, '$.name') Unit
    , cast(json_extract_scalar(inventory, '$.netWeight') as float64) Weight
    --WebshopArticle not available
    , if(description='', null, description) Note
    , cast(costPrice as float64) DirectCost
    --FreightCost, OtherCost, PurchaseAccount, StockChangeAccount, DefaultStockPoint, DefaultStockLocation, CommodityCode not available
  from {{ source('visma_economic_api', 'products') }}
)

select
  ArticleId
  , ArticleNumber
  , cast(Description as STRING) as ArticleName
  , cast(null as STRING) as Manufacturer
  , PurchasePrice
  , cast(null as BOOLEAN) as StockGoods
  , QuantityInStock
  , cast(null as STRING) as SupplierName
  , cast(null as STRING) as SupplierNumber
  , cast(null as BOOLEAN) as isActive
  , {{ add_erp_fields(columns=['ArticleId']) }}
from main