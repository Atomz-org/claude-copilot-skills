{{ config(alias=(model_alias(model.name))) }}
with articles as (
  select
    '1111111111' OrgId
    , ArticleNumber
    , Bulky
    , Housework
    , PurchasePrice * {{ global_configs('demo_multi') }} PurchasePrice
    , QuantityInStock * {{ global_configs('demo_multi') }} QuantityInStock
    , ReservedQuantity * {{ global_configs('demo_multi') }} ReservedQuantity
    , SalesPrice * {{ global_configs('demo_multi') }} SalesPrice
    , StockGoods
    , StockValue * {{ global_configs('demo_multi') }} StockValue
    , Type
    , Unit
    , VAT * {{ global_configs('demo_multi') }} VAT
    , DirectCost * {{ global_configs('demo_multi') }} DirectCost
    , FreightCost * {{ global_configs('demo_multi') }} FreightCost
    , OtherCost * {{ global_configs('demo_multi') }} OtherCost
    , Active
    , row_number() over(order by ArticleNumber asc) rn
  from {{ source('fortnox_api_demo', 'articles') }}
  where OrgId = (select min(OrgId) from {{ source('fortnox_api_demo', 'articles') }})
  group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17
)
select
  OrgId
  , cast(null as string) Url
  , cast(rn as string) ArticleNumber
  , Bulky
  , 0 ConstructionAccount
  , 0 Depth
  , 'Article #' || rn Description
  , 0 DisposableQuantity
  , cast(null as string) EAN
  , 0 EUAccount
  , 0 EUVATAccount
  , 0 ExportAccount
  , null Height
  , Housework
  , cast(null as string) HouseworkType
  , cast(null as string) Manufacturer
  , cast(null as string) ManufacturerArticleNumber
  , cast(null as string) Note
  , 0 PurchaseAccount
  , PurchasePrice
  , QuantityInStock
  , ReservedQuantity
  , 0 SalesAccount
  , SalesPrice
  , StockGoods
  , cast(null as string) StockPlace
  , StockValue
  , null StockWarning
  , cast(null as string) SupplierName
  , cast(null as string) SupplierNumber
  , Type
  , Unit
  , VAT
  , FALSE WebshopArticle
  , 0 Weight
  , 0 Width
  , FALSE Expired
  , cast(null as string) CostCalculationMethod
  , 0 StockAccount
  , 0 StockChangeAccount
  , DirectCost
  , FreightCost
  , OtherCost
  , cast(null as string) DefaultStockPoint
  , cast(null as string) DefaultStockLocation
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , Active
  , cast(null as string) CommodityCode
  , 'Success' ENZ_DEBUG_INFO
  , cast(null as json) Bundle
  , FALSE BundleArticle
from articles