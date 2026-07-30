{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
   OfferNo
  , OfferId
  , OfferDate
  , DeliveryDate
  , ExpireDate
  , OurReference
  , YourReference
  , Sent
  , NotCompleted
  , OrderReference
  , InvoiceReference
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
  , CopyRemarks 
  , Country
  , Labels
  , OrgId
  , CustomerId
  , ProjectId
  , CostCenterId
  , {{ add_erp_fields(columns=['OfferId', 'OrgId', 'CustomerId', 'ProjectId', 'CostCenterId']) }}
from {{ ref('fortnox_bi_fact_offers_staging') }}