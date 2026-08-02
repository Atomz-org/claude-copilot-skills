{{ config(materialized='ephemeral', enabled = var('is_upsales_enabled', false)) }}

with main as (
select
  OrgId || '-' || id ArticleId
  , cast(id as string) ArticleNumber
  , name Description
  --Manufacturer, ManufacturerArticleNumber, EAN not available
  , active Active
  , purchaseCost PurchasePrice
  --QuantityInStock, ReservedQuantity not available
  , listPrice SalesPrice
  --StockGoods, StockPlace, StockValue, StockWarning, SupplierName, SupplierNumber not available
  , json_extract_scalar(category, '$.name') Type
  --Unit, Weight, WebshopArticle not available
  , articleNo Note
  , purchaseCost DirectCost
  --FreightCost, OtherCost, PurchaseAccount, StockChangeAccount, DefaultStockPoint, DefaultStockLocation, CommodityCode not available
from {{ source('upsales_api', 'products') }}
)

select
  ArticleId
  , ArticleNumber
  , cast(Description as STRING) as ArticleName
  , cast(null as STRING) as Manufacturer
  , PurchasePrice
  , cast(null as BOOLEAN) as StockGoods
  , cast(null as FLOAT64) as QuantityInStock
  , cast(null as STRING) as SupplierName
  , cast(null as STRING) as SupplierNumber
  , Active
  , {{ add_erp_fields(columns=['ArticleId']) }}
from main