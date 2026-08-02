{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  OrderNo
  , OrderId
  , InvoiceReference
  , OfferReference
  , OrderDate
  , OutboundDate
  , OrderType
  , DeliveryDate
  , DeliveryState
  , OurReference
  , YourOrderNumber
  , YourReference
  , Sent
  , NotCompleted
  , HouseWork
  , Currency
  , CurrencyRate
  , Freight
  , AdministrationFee
  , TotalVAT
  , Net
  , TaxReduction
  , Gross
  , RoundOff
  , TotalToPay
  , ContributionPercent
  , ContributionValue
  , TermsOfDelivery
  , TermsOfPayment
  , WayOfDelivery
  , DeliveryAddress1
  , DeliveryAddress2
  , DeliveryCity
  , DeliveryCountry
  , DeliveryZipCode
  , DeliveryName
  , RecipientEmail
  , RecipientPhone
  , Comments
  , hasCopyRemarks
  , ExternalInvoiceReference1
  , ExternalInvoiceReference2
  , Country
  , isWarehouseReady
  , Labels
  , OrgId
  , CustomerId
  , StockPointId
  , LabelId
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'LabelId','CustomerId', 'StockPointId']) }}
from {{ ref('fortnox_bi_fact_orders_staging') }}