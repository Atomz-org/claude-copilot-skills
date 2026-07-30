{{ config(alias=(model_alias(model.name))) }}

with org as (
  select
    min(OrgId) OrgId
  from {{ source('fortnox_api_demo', 'v2_offers') }}
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
  group by 1
)

, orders as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_orders') }}
  where OrgId = (select OrgId from org)
  group by 1
)

, offer_no as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_offers') }}
  where OrgId = (select OrgId from org)
    and extract(year from OfferDate) in ( 
      {{ global_configs('demo_max_year') }}
      , {{ global_configs('demo_max_year') }} - 1 
    )
)

, offer_rows_raw as (
  select
    DocumentNumber
    , cast(json_extract_scalar(r, '$.AccountNumber') as int64) AccountNumber
    , json_extract_scalar(r, '$.ArticleNumber') ArticleNumber
    -- , json_extract_scalar(r, '$.Bundle') Bundle
    , json_extract_scalar(r, '$.ContributionPercent') ContributionPercent 
    , cast(cast(json_extract_scalar(r, '$.ContributionValue') as float64) * {{ global_configs('demo_multi') }} as string) ContributionValue
    -- , json_extract_scalar(r, '$.CostCenter') CostCenter
    -- , json_extract_scalar(r, '$.Description') Description
    , cast(json_extract_scalar(r, '$.Discount') as float64) Discount
    , json_extract_scalar(r, '$.DiscountType') DiscountType
    , json_extract_scalar(r, '$.HouseWork') HouseWork
    , json_extract_scalar(r, '$.HouseWorkHoursToReport') HouseWorkHoursToReport
    , json_extract_scalar(r, '$.HouseWorkType') HouseWorkType
    , cast(json_extract_scalar(r, '$.Price') as float64) * {{ global_configs('demo_multi') }} Price
    -- , json_extract_scalar(r, '$.Project') Project
    , json_extract_scalar(r, '$.Quantity') Quantity
    , json_extract_scalar(r, '$.RowId') RowId
    , cast(json_extract_scalar(r, '$.Total') as float64) * {{ global_configs('demo_multi') }} Total
    , json_extract_scalar(r, '$.Unit') Unit
    , cast(json_extract_scalar(r, '$.VAT') as float64) * {{ global_configs('demo_multi') }} VAT
  from {{ source('fortnox_api_demo', 'v2_offers') }}
  , unnest(json_extract_array(OfferRows)) r
  where OrgId in (select OrgId from org)
    and DocumentNumber in (select DocumentNumber from offer_no)
)

, offer_rows as (
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
          , cast(null as string) as CostCenter
          , "" as Description
          , Discount
          , DiscountType
          , HouseWork
          , HouseWorkHoursToReport
          , HouseWorkType
          , Price
          , "" as Project
          , Quantity
          , RowId
          , Total
          , Unit
          , VAT
        )
      )
    , ', ') || ']' OfferRows
  from offer_rows_raw
  left join articles
    on articles.ArticleNumber = offer_rows_raw.ArticleNumber
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
  from offer_no
  group by 1
)

, offers as (
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
    , {{ demo_date('ExpireDate') }} ExpireDate
    , Freight * {{ global_configs('demo_multi') }} Freight
    , FreightVAT * {{ global_configs('demo_multi') }} FreightVAT
    , Gross * {{ global_configs('demo_multi') }} Gross
    , o.HouseWork o_HouseWork
    , InvoiceReference
    , Net * {{ global_configs('demo_multi') }} Net
    , NotCompleted
    , {{ demo_date('OfferDate') }} OfferDate
    , OrderReference
    , o.`Project`
    , RoundOff * {{ global_configs('demo_multi') }} RoundOff
    , Sent
    , TaxReduction * {{ global_configs('demo_multi') }} TaxReduction
    , o.Total * {{ global_configs('demo_multi') }}  o_Total
    , TotalToPay * {{ global_configs('demo_multi') }} TotalToPay
    , TotalVAT * {{ global_configs('demo_multi') }} TotalVAT
    , VATIncluded
    , TaxReductionType
  from {{ source('fortnox_api_demo', 'v2_offers') }} o
  where OrgId in (select OrgId from org)
    and DocumentNumber in (select DocumentNumber from offer_no)
)
select
  '1111111111' OrgId
  , AdministrationFee
  , AdministrationFeeVAT
  , cast(null as string) Address1
  , cast(null as string) Address2
  , BasisTaxReduction
  , Cancelled
  , 'Stockholm' City
  , cast(null as string) Comments
  , o_ContributionPercent ContributionPercent
  , o_ContributionValue ContributionValue
  , FALSE CopyRemarks
  , 'Sweden' Country
  , cast(cstcntr.rn * 100 as string) CostCenter
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
  , cast(null as string) DeliveryZipCode
  , cast(offer_no.rn as string) DocumentNumber
  , cast(null as string) EmailAddressFrom
  , cast(null as string) EmailAddressTo
  , cast(null as string) EmailAddressCC
  , cast(null as string) EmailAddressBCC
  , cast(null as string) EmailSubject
  , cast(null as string) EmailBody
  , cast(null as json) EmailInformation
  , ExpireDate
  , Freight
  , FreightVAT
  , Gross
  , o_HouseWork HouseWork
  , cast(invoices.rn as string) InvoiceReference
  , labels.Labels
  , 'SV' `Language`
  , Net
  , NotCompleted
  , OfferDate
  , ofrw.OfferRows
  , cast(orders.rn as string) OrderReference
  , cast(null as string) OrganisationNumber
  , 'Sales rep #' || round(rand()*10, 0) OurReference
  , cast(null as string) Phone1
  , cast(null as string) Phone2
  , cast(null as string) PriceList
  , cast(null as string) PrintTemplate
  , cast(prjct.rn * 100 as string) `Project`
  , cast(null as string) Remarks
  , RoundOff
  , Sent
  , TaxReduction
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , o_Total Total
  , TotalToPay
  , TotalVAT
  , VATIncluded
  , cast(null as string) WayOfDelivery
  , cast(null as string) YourReference
  , cast(null as string) YourReferenceNumber
  , cast(round(rand() * 10000, 0) as string) ZipCode
  , TaxReductionType
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO
from offers
left join offer_no
  on offer_no.DocumentNumber = offers.DocumentNumber
left join offer_rows ofrw
  on ofrw.DocumentNumber = offers.DocumentNumber
left join cstcntr
  on cstcntr.Code = offers.CostCenter
left join customers
  on customers.CustomerNumber = offers.CustomerNumber
left join invoices
  on cast(invoices.DocumentNumber as string) = offers.InvoiceReference
left join orders
  on cast(orders.DocumentNumber as string) = offers.OrderReference
left join prjct
  on prjct.ProjectNumber = offers.Project
left join labels
  on labels.DocumentNumber = offers.DocumentNumber