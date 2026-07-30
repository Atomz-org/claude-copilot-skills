{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with stocks as (
  select
    distinct OrgId
    , ItemId
    , sum(InStock) InStock
    , sum(AvailableStock) AvailableStock
  from {{ source('fortnox_api', 'stockbalance') }}
  group by 1,2
)

select
  a.OrgId
  , a.OrgId || '-' || {{ blank_to_null('ArticleNumber') }} as ArticleId
  , ArticleNumber
  , IFNULL(Description, "[unknown]") as Description
  , Manufacturer
  , ManufacturerArticleNumber
  , EAN
  , Active
  , PurchasePrice
  , coalesce(sb.InStock, 0) QuantityInStock
  , ifnull(sb.InStock,0) - ifnull(sb.AvailableStock, 0) ReservedQuantity
  , DisposableQuantity
  , SalesPrice
  , StockGoods
  , StockPlace
  , StockValue
  , StockWarning
  , SupplierName
  , SupplierNumber
  , Type
  , Unit
  , Weight
  , cast(Width as float64) Width
  , cast(Height as float64) Height
  , cast(Depth as float64) Depth
  , WebshopArticle
  , Note
  , DirectCost
  , FreightCost
  , OtherCost
  , PurchaseAccount
  , StockChangeAccount
  , StockAccount
  , SalesAccount
  , ConstructionAccount
  , EUAccount
  , EUVATAccount
  , ExportAccount
  , VAT
  , DefaultStockPoint
  , DefaultStockLocation
  , CommodityCode
  , BundleArticle isBundleParent
  , case
    when a.OrgId || '-' || ArticleNumber in (
      select distinct
        OrgId || '-' || json_extract_scalar(r, '$.ArticleNumber') ArticleId
      from {{ source('fortnox_api', 'articles') }} a
      , unnest(json_extract_array(a.Bundle, '$.SubItems')) r
      where BundleArticle is TRUE
    )
      then TRUE
    else FALSE
  end isBundleSubItem
from
  {{ source('fortnox_api', 'articles') }} a
left join stocks sb
  on sb.OrgId = a.OrgId 
  and sb.ItemId = a.ArticleNumber