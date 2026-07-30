{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with main as (
  select
    OrgId || '-' || Id ArticleId
    , Number ArticleNumber
    , IFNULL(Name, "[unknown]") ArticleName
    --Manufacturer, ManufacturerArticleNumber and EAN are not available
    , IsActive Active
    , PurchasePrice
    , StockBalanceAvailable QuantityInStock
    , StockBalanceReserved ReservedQuantity
    , if(NetPriceWithDiscount=0, NetPrice, NetPriceWithDiscount) SalesPrice
    --, GrossPrice
    , IsStock StockGoods
    , StockLocationReference StockPlace
    , StockValue
    --StockWarning, SupplierName, SupplierNumber are not available
    , if(IsStock, 'STOCK', if(IsServiceArticle, 'SERVICE', 'OTHER')) Type
    , UnitAbbreviation Unit
    -- Weight is not available
    , SendToWebshop WebshopArticle
    --!!Note under investigation!!
    --DirectCost is not available
    , FreightCosts FreightCost
    --OtherCost, PurchaseAccount, StockChangeAccount, DefaultStockPoint, DefaultStockLocation and CommodityCode are not available
  from
    {{ source('visma_eaccounting_api', 'articles') }}
)

select
  ArticleId
  , ArticleNumber
  , ArticleName
  , cast(null as STRING) as Manufacturer
  , PurchasePrice
  , StockGoods
  , QuantityInStock
  , cast(null as STRING) as SupplierName
  , cast(null as STRING) as SupplierNumber
  , Active
, {{ add_erp_fields(columns=['ArticleId']) }}
from main