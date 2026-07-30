{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with main as (
  select
    OrgId || '-' || _id ArticleId
    , if(articleNumber='', null, articleNumber) ArticleNumber
    , {{ blank_to_null('name') }} ArticleName
    --Manufacturer, ManufacturerArticleNumber, EAN not available
    , isActive Active
    , unitCost PurchasePrice
    --QuantityInStock, ReservedQuantity not available
    , unitPrice SalesPrice
    --StockGoods, StockPlace, StockValue, StockWarning,
    , distributorName SupplierName
    , distributor SupplierNumber
    --Type not available
    , unit Unit
    --Weight, WebshopArticle not available
    , {{ blank_to_null('description') }} Note
    -- DirectCost, FreightCost, OtherCost, PurchaseAccount, StockChangeAccount, DefaultStockPoint, DefaultStockLocation, CommodityCode, GrossPrice not available
  from {{ source('seventime_api', 'expenseitems') }}
)
select
  ArticleId
  , ArticleNumber
  , ArticleName
  , cast(null as STRING) as Manufacturer
  , PurchasePrice
  , cast(null as BOOLEAN) as StockGoods
  , cast(null as FLOAT64) as QuantityInStock
  , SupplierName
  , SupplierNumber
  , Active
  , {{ add_erp_fields(columns=['ArticleId']) }}
from main