{{ config(alias=(model_alias(model.name))) }}

with org as (
  select
    min(OrgId) OrgId
  from {{ source('fortnox_api_demo', 'v2_orders') }}
)

, cstcntr as (
  select
    Code
    , row_number() over(order by Code asc) rn
  from {{ source('fortnox_api_demo', 'cost_centers') }}
  where OrgId = (select OrgId from org)
  group by 1
)

, prjct as (
  select
    ProjectNumber
    , row_number() over(order by ProjectNumber asc) rn
  from {{ source('fortnox_api_demo', 'projects') }}
  where OrgId = (select OrgId from org)
  group by 1
)

, customers as (
  select
    CustomerNumber
    , row_number() over(order by CustomerNumber asc) rn
  from {{ source('fortnox_api_demo', 'customers') }}
  where OrgId = (select OrgId from org)
  group by 1
)

, articles as (
  select
    ArticleNumber
    , row_number() over(order by ArticleNumber asc) rn
  from {{ source('fortnox_api_demo', 'articles') }}
  where OrgId = (select OrgId from org)
  group by 1
)

, invoices as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_invoices') }}
  where OrgId = (select OrgId from org)
    and extract(year from InvoiceDate) in ( 
      {{ global_configs('demo_max_year') }}
      , {{ global_configs('demo_max_year') }} - 1 
    )
  group by 1
)

, offers as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_offers') }}
  where OrgId = (select OrgId from org)
  group by 1
)

, order_no as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_orders') }}
  where OrgId = (select OrgId from org)
    and extract(year from OrderDate) in ( 
      {{ global_configs('demo_max_year') }}
      , {{ global_configs('demo_max_year') }} - 1 
    )
)

, order_rows_raw as (
  select
    DocumentNumber
    , cast(json_extract_scalar(r, '$.AccountNumber') as int64) AccountNumber
    , json_extract_scalar(r, '$.ArticleNumber') ArticleNumber
    -- , json_extract_scalar(r, '$.Bundle') Bundle
    , json_extract_scalar(r, '$.ContributionPercent') ContributionPercent 
    , cast(cast(json_extract_scalar(r, '$.ContributionValue') as float64) * {{ global_configs('demo_multi') }} as string) ContributionValue
    -- , json_extract_scalar(r, '$.Cost') Cost !!!!!!!!!!! 
    -- , json_extract_scalar(r, '$.CostCenter') CostCenter
    , json_extract_scalar(r, '$.DeliveredQuantity') DeliveredQuantity
    -- , json_extract_scalar(r, '$.Description') Description
    , cast(json_extract_scalar(r, '$.Discount') as float64) Discount
    , json_extract_scalar(r, '$.DiscountType') DiscountType
    , json_extract_scalar(r, '$.HouseWork') HouseWork
    , json_extract_scalar(r, '$.HouseWorkHoursToReport') HouseWorkHoursToReport
    , json_extract_scalar(r, '$.HouseWorkType') HouseWorkType
    , json_extract_scalar(r, '$.OrderedQuantity') OrderedQuantity
    , cast(json_extract_scalar(r, '$.Price') as float64) * {{ global_configs('demo_multi') }} Price
    -- , json_extract_scalar(r, '$.Project') Project !!!!!!!!!!! 
    , json_extract_scalar(r, '$.ReservedQuantity') ReservedQuantity
    , json_extract_scalar(r, '$.RowId') RowId
    --, json_extract_scalar(r, '$.StockPointCode') StockPointCode !!!!!!!!!!! 
    --, json_extract_scalar(r, '$.StockPointId') StockPointId !!!!!!!!!!! 
    , cast(json_extract_scalar(r, '$.Total') as float64) * {{ global_configs('demo_multi') }} Total
    , json_extract_scalar(r, '$.Unit') Unit
    , cast(json_extract_scalar(r, '$.VAT') as float64) * {{ global_configs('demo_multi') }} VAT
  from {{ source('fortnox_api_demo', 'v2_orders') }}
  , unnest(json_extract_array(OrderRows)) r
  where OrgId in (select OrgId from org)
    and DocumentNumber in (select DocumentNumber from order_no)
)

, order_rows as (
  select
    DocumentNumber
    , '[' || string_agg(
      to_json_string(
        struct(
          AccountNumber
          , articles.rn as ArticleNumber
          , cast(null as boolean) as Bundle
          , ContributionPercent
          , ContributionValue
          , cast(null as string) as Cost
          , cast(null as string) as CostCenter
          , DeliveredQuantity
          , "" as Description
          , Discount
          , DiscountType
          , HouseWork
          , HouseWorkHoursToReport
          , HouseWorkType
          , OrderedQuantity
          , Price
          , "" as Project
          , ReservedQuantity
          , RowId
          , cast(null as string) as StockPointCode
          , cast(null as string) as StockPointId
          , Total
          , Unit
          , VAT
        )
      )
    , ', ') || ']' OrderRows
  from order_rows_raw
  left join articles
    on articles.ArticleNumber = order_rows_raw.ArticleNumber
  group by 1
)

, labels as (
  select
    DocumentNumber
    , '[' || string_agg(
      to_json_string(
        struct(
          null as id
        )
      )
    , ', ') || ']' Labels
  from order_no
  group by 1
)

, orders as (
  select
    AdministrationFee * {{ global_configs('demo_multi') }} AdministrationFee
    , AdministrationFeeVAT * {{ global_configs('demo_multi') }} AdministrationFeeVAT
    , BasisTaxReduction * {{ global_configs('demo_multi') }} BasisTaxReduction
    , Cancelled
    , o.ContributionPercent o_ContributionPercent
    , o.ContributionValue * {{ global_configs('demo_multi') }} o_ContributionValue
    , o.CostCenter
    , Currency
    , CurrencyRate
    , CurrencyUnit
    , CustomerNumber
    , {{ demo_date('DeliveryDate') }} DeliveryDate
    , DocumentNumber
    , InvoiceReference
    , Freight * {{ global_configs('demo_multi') }} Freight
    , FreightVAT * {{ global_configs('demo_multi') }} FreightVAT
    , Gross * {{ global_configs('demo_multi') }} Gross
    , o.HouseWork o_HouseWork
    , Net * {{ global_configs('demo_multi') }} Net
    , NotCompleted
    , {{ demo_date('OrderDate') }} OrderDate
    , OfferReference
    , OrderType
    , o.`Project`
    , WarehouseReady
    , {{ demo_date('OutboundDate') }} OutboundDate
    , RoundOff * {{ global_configs('demo_multi') }} RoundOff
    , Sent
    , TaxReduction * {{ global_configs('demo_multi') }} TaxReduction
    , o.Total * {{ global_configs('demo_multi') }}  o_Total
    , TotalToPay * {{ global_configs('demo_multi') }} TotalToPay
    , TotalVAT * {{ global_configs('demo_multi') }} TotalVAT
    , VATIncluded
    , TaxReductionType
  from {{ source('fortnox_api_demo', 'v2_orders') }} o
  where OrgId in (select OrgId from org)
    and DocumentNumber in (select DocumentNumber from order_no)
)
select
  '1111111111' OrgId
  , cast(null as string) Address1
  , cast(null as string) Address2
  , AdministrationFee
  , AdministrationFeeVAT
  , BasisTaxReduction
  , Cancelled
  , 'Stockholm' City
  , cast(null as string) Comments
  , o_ContributionPercent ContributionPercent
  , o_ContributionValue ContributionValue
  , FALSE CopyRemarks
  , cast(cstcntr.rn * 100 as string) CostCenter
  , 'Sweden' Country
  , Currency
  , CurrencyRate
  , CurrencyUnit
  , 'Customer #' || customers.rn CustomerName
  , cast(customers.rn as string) CustomerNumber
  , cast(null as string) DeliveryAddress1
  , cast(null as string) DeliveryAddress2
  , 'Stockholm' DeliveryCity
  , 'Sweden' DeliveryCountry
  , DeliveryDate
  , cast(null as string) DeliveryName
  , 'delivery' DeliveryState
  , cast(null as string) DeliveryZipCode
  , cast(order_no.rn as string) DocumentNumber
  , cast(null as json) EmailInformation
  , cast(null as string) ExternalInvoiceReference1
  , cast(null as string) ExternalInvoiceReference2
  , Freight
  , FreightVAT
  , Gross
  , o_HouseWork HouseWork
  , cast(invoices.rn as string) InvoiceReference
  , labels.Labels
  , 'SV' `Language`
  , Net
  , NotCompleted
  , cast(offers.rn as string) OfferReference 
  , OrderDate
  , ofrw.OrderRows
  , OrderType
  , cast(null as string) OrganisationNumber
  , 'Sales rep #' || round(rand()*10, 0) OurReference
  , OutboundDate
  , cast(null as string) Phone1
  , cast(null as string) Phone2
  , cast(null as string) PriceList
  , cast(null as string) PrintTemplate
  , cast(prjct.rn * 100 as string) `Project`
  , cast(null as string) Remarks
  , RoundOff
  , Sent
  , cast(null as string) StockPointCode
  , cast(null as string) StockPointId
  , TaxReduction
  , TaxReductionType
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , cast(null as string) TimeBasisReference
  , o_Total Total
  , TotalToPay
  , TotalVAT
  , VATIncluded
  , WarehouseReady
  , cast(null as string) WayOfDelivery
  , cast(null as string) YourOrderNumber
  , cast(null as string) YourReference
  , cast(round(rand() * 10000, 0) as string) ZipCode
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO
from orders
left join order_no
  on order_no.DocumentNumber = orders.DocumentNumber
left join order_rows ofrw
  on ofrw.DocumentNumber = orders.DocumentNumber
left join cstcntr
  on cstcntr.Code = orders.CostCenter
left join customers
  on customers.CustomerNumber = orders.CustomerNumber
left join invoices
  on cast(invoices.DocumentNumber as string) = orders.InvoiceReference
left join offers
  on cast(offers.DocumentNumber as string) = orders.OfferReference
left join prjct
  on prjct.ProjectNumber = orders.Project
left join labels
  on labels.DocumentNumber = orders.DocumentNumber