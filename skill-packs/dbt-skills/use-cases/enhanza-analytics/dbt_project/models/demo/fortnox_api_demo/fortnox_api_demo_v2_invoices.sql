{{ config(alias=(model_alias(model.name))) }}

with org as (
  select
    min(OrgId) OrgId
  from {{ source('fortnox_api_demo', 'v2_invoices') }}
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

, offers as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_offers') }}
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

, invoice_no as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_invoices') }}
  where OrgId = (select OrgId from org)
    and extract(year from InvoiceDate) in ( 
      {{ global_configs('demo_max_year') }}
      , {{ global_configs('demo_max_year') }} - 1 
    )
)

, invoice_rows_raw as (
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
    , cast(json_extract_scalar(r, '$.Price') as float64) * {{ global_configs('demo_multi') }} Price
    , cast(json_extract_scalar(r, '$.PriceExcludingVAT') as float64) * {{ global_configs('demo_multi') }} PriceExcludingVAT
    -- , json_extract_scalar(r, '$.Project') Project !!!!!!!!!!! 
    , json_extract_scalar(r, '$.RowId') RowId
    --, json_extract_scalar(r, '$.StockPointCode') StockPointCode !!!!!!!!!!! 
    , cast(json_extract_scalar(r, '$.Total') as float64) * {{ global_configs('demo_multi') }} Total
    , cast(json_extract_scalar(r, '$.TotalExcludingVAT') as float64) * {{ global_configs('demo_multi') }} TotalExcludingVAT
    , json_extract_scalar(r, '$.Unit') Unit
    , cast(json_extract_scalar(r, '$.VAT') as float64) * {{ global_configs('demo_multi') }} VAT
  from {{ source('fortnox_api_demo', 'v2_invoices') }}
  , unnest(json_extract_array(InvoiceRows)) r
  where OrgId in (select OrgId from org)
    and DocumentNumber in (select DocumentNumber from invoice_no)
)

, invoice_rows as (
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
          , Price
          , PriceExcludingVAT
          , "" as Project
          , RowId
          , cast(null as string) as StockPointCode
          , Total
          , TotalExcludingVAT
          , Unit
          , VAT
        )
      )
    , ', ') || ']' InvoiceRows
  from invoice_rows_raw
  left join articles
    on articles.ArticleNumber = invoice_rows_raw.ArticleNumber
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
  from invoice_no
  group by 1
)

, invoices as (
  select
    AdministrationFee * {{ global_configs('demo_multi') }} AdministrationFee
    , AdministrationFeeVAT * {{ global_configs('demo_multi') }} AdministrationFeeVAT
    , Balance * {{ global_configs('demo_multi') }} Balance
    , BasisTaxReduction * {{ global_configs('demo_multi') }} BasisTaxReduction
    , Booked
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
    , {{ demo_date('DueDate') }} DueDate
    , Freight * {{ global_configs('demo_multi') }} Freight
    , FreightVAT * {{ global_configs('demo_multi') }} FreightVAT
    , Gross * {{ global_configs('demo_multi') }} Gross
    , o.HouseWork o_HouseWork
    , {{ demo_date('InvoiceDate') }} InvoiceDate
    , {{ demo_date('InvoicePeriodStart') }} InvoicePeriodStart
    , {{ demo_date('InvoicePeriodEnd') }} InvoicePeriodEnd
    , InvoiceType
    , {{ demo_date('LastRemindDate') }} LastRemindDate
    , Net * {{ global_configs('demo_multi') }} Net
    , NotCompleted
    , OfferReference
    , OrderReference
    , o.`Project`
    , WarehouseReady
    , {{ demo_date('OutboundDate') }} OutboundDate
    , Reminders
    , RoundOff * {{ global_configs('demo_multi') }} RoundOff
    , Sent
    , TaxReduction * {{ global_configs('demo_multi') }} TaxReduction
    , o.Total * {{ global_configs('demo_multi') }}  o_Total
    , TotalToPay * {{ global_configs('demo_multi') }} TotalToPay
    , TotalVAT * {{ global_configs('demo_multi') }} TotalVAT
    , VATIncluded
    , VoucherNumber * ({{ var('demo_multi', 2) }} -1) VoucherNumber
    , VoucherSeries
    , VoucherYear
    , {{ demo_date('FinalPayDate') }} FinalPayDate
    , TaxReductionType
  from {{ source('fortnox_api_demo', 'v2_invoices') }} o
  where OrgId in (select OrgId from org)
    and DocumentNumber in (select DocumentNumber from invoice_no)
)

select
  '1111111111' OrgId
  , 'ACCRUAL' AccountingMethod
  , cast(null as string) Address1
  , cast(null as string) Address2
  , AdministrationFee
  , AdministrationFeeVAT
  , Balance
  , BasisTaxReduction
  , Booked
  , Cancelled
  , 'Stockholm' City
  , cast(null as string) Comments
  , 0 ContractReference
  , o_ContributionPercent ContributionPercent
  , o_ContributionValue ContributionValue
  , cast(cstcntr.rn * 100 as string) CostCenter
  , 'Sweden' Country
  , FALSE Credit
  , '0' CreditInvoiceReference
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
  , cast(invoice_no.rn as string) DocumentNumber
  , DueDate
  , cast(null as json) EDIInformation
  , FALSE EUQuarterlyReport
  , cast(null as json) EmailInformation
  , cast(null as string) ExternalInvoiceReference1
  , cast(null as string) ExternalInvoiceReference2
  , FinalPayDate
  , Freight
  , FreightVAT
  , Gross
  , o_HouseWork HouseWork
  , InvoiceDate
  , InvoicePeriodEnd
  , cast(null as string) InvoicePeriodReference
  , InvoicePeriodStart
  , ofrw.InvoiceRows
  , InvoiceType
  , labels.Labels
  , 'SV' `Language`
  , LastRemindDate
  , Net
  , NotCompleted
  , FALSE NoxFinans
  , cast(null as string) OCR
  , cast(offers.rn as string) OfferReference 
  , cast(orders.rn as string) OrderReference 
  , cast(null as string) OrganisationNumber
  , 'Sales rep #' || round(rand()*10, 0) OurReference
  , OutboundDate
  , "" PaymentWay
  , cast(null as string) Phone1
  , cast(null as string) Phone2
  , cast(null as string) PriceList
  , cast(null as string) PrintTemplate
  , cast(prjct.rn * 100 as string) `Project`
  , cast(null as string) Remarks
  , Reminders
  , RoundOff
  , Sent
  , TaxReduction
  , TaxReductionType
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , cast(null as string) TimeBasisReference
  , o_Total Total
  , TotalToPay
  , TotalVAT
  , VATIncluded
  , VoucherNumber
  , VoucherSeries
  , VoucherYear
  , WarehouseReady
  , cast(null as string) WayOfDelivery
  , cast(null as string) YourOrderNumber
  , cast(null as string) YourReference
  , cast(round(rand() * 10000, 0) as string) ZipCode
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO
from invoices
left join invoice_no
  on invoice_no.DocumentNumber = invoices.DocumentNumber
left join invoice_rows ofrw
  on ofrw.DocumentNumber = invoices.DocumentNumber
left join cstcntr
  on cstcntr.Code = invoices.CostCenter
left join customers
  on customers.CustomerNumber = invoices.CustomerNumber
left join orders
  on cast(orders.DocumentNumber as string) = invoices.OrderReference
left join offers
  on cast(offers.DocumentNumber as string) = invoices.OfferReference
left join prjct
  on prjct.ProjectNumber = invoices.Project
left join labels
  on labels.DocumentNumber = invoices.DocumentNumber