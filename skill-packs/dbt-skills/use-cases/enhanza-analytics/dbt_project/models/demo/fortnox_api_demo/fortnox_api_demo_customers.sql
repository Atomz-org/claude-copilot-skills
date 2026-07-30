{{ config(alias=(model_alias(model.name))) }}
with customers as (
  select
    CustomerNumber
    , row_number() over(order by CustomerNumber asc) rn
  from {{ source('fortnox_api_demo', 'customers') }}
  where OrgId = (select min(OrgId) from {{ source('fortnox_api_demo', 'customers') }})
  group by 1
)
select
  '1111111111' OrgId
  , cast(null as string) Url
  , TRUE Active
  , cast(null as string) Address1
  , cast(null as string) Address2
  , 'Stockholm' City
  , cast(null as string) Comments
  , cast(null as string) CostCenter
  , 'Sweden' Country
  , 'SE' CountryCode
  , 'SEK' Currency
  , cast(rn as string) CustomerNumber
  , struct(
    'PRINT' as Invoice
    , 'PRINT' as `Order`
    , 'PRINT' as Offer
  ) DefaultDeliveryTypes
  , struct(
    'DEFAULTTEMPLATE' as Invoice
    , 'DEFAULTTEMPLATE' as `Order`
    , 'DEFAULTTEMPLATE' as Offer
    , 'DEFAULTTEMPLATE' as CashInvoice
  ) DefaultTemplates
  , cast(null as string) DeliveryAddress1
  , cast(null as string) DeliveryAddress2
  , cast(null as string) DeliveryCity
  , cast(null as string) DeliveryCountry
  , cast(null as string) DeliveryCountryCode
  , cast(null as string) DeliveryFax
  , cast(null as string) DeliveryName
  , cast(null as string) DeliveryPhone1
  , cast(null as string) DeliveryPhone2
  , cast(null as string) DeliveryZipCode
  , 'customer' || rn || '@example.com' Email
  , cast(null as string) EmailInvoice
  , cast(null as string) EmailInvoiceBCC
  , cast(null as string) EmailInvoiceCC
  , cast(null as string) EmailOffer
  , cast(null as string) EmailOfferBCC
  , cast(null as string) EmailOfferCC
  , cast(null as string) EmailOrder
  , cast(null as string) EmailOrderBCC
  , cast(null as string) EmailOrderCC
  , cast(null as string) Fax
  , cast(null as string) GLN
  , cast(null as string) GLNDelivery
  , 0.0 InvoiceAdministrationFee
  , 0.0 InvoiceDiscount
  , 0.0 InvoiceFreight
  , cast(null as string) InvoiceRemark
  , 'Customer #' || rn Name
  , left(cast(rn * 1111111111 as string), 6) || '-' || right(cast(rn * 1111111111 as string), 4) OrganisationNumber
  , 'Sales rep #' || round(rand()*10, 0) OurReference
  , cast(null as string) Phone1
  , cast(null as string) Phone2
  , cast(null as string) PriceList
  , cast(null as string) Project
  , cast(null as string) SalesAccount
  , FALSE ShowPriceVATIncluded
  , cast(null as string) TermsOfDelivery
  , cast(null as string) TermsOfPayment
  , 'COMPANY' Type
  , cast(null as string) VATNumber
  , 'SEVAT' VATType
  , cast(null as string) VisitingAddress
  , cast(null as string) VisitingCity
  , cast(null as string) VisitingCountry
  , cast(null as string) VisitingCountryCode
  , cast(null as string) VisitingZipCode
  , cast(null as string) WWW
  , cast(null as string) WayOfDelivery
  , cast(null as string) YourReference
  , cast(round(rand() * 10000, 0) as string) ZipCode
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO
from customers