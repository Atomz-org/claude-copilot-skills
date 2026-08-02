{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  CustomerId
  , CustomerNumber
  , Name
  , OrganisationNumber
  , Address
  , ZipCode
  , Phone
  , AdditionalPhone
  , Email
  , Website
  , Fax
  , City
  , Type
  , isActive
  , Country
  , Comments
  , OurReference
  , YourReference
  , DefaultTemplate
  , DefaultVATType
  , TemplateReference
  , DefaultDeliveryType
  , DeliveryCountry
  , DeliveryCity
  , DeliveryAddress1
  , DeliveryAddress2
  , DeliveryName
  , DeliveryPhone1
  , DeliveryPhone2
  , DeliveryZipCode
  , DeliveryFax
  , VisitingAddress
  , VisitingCity
  , VisitingCountry
  , TermsOfPayment
  , EmailInvoice
  , InvoiceRemark
  , VATNumber
  , PriceListId
  , CostCenterId
  , ProjectId
  , FirstInvoiceDate
  , LastInvoiceDate
  , InvoiceDiscount
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_dim_customers_staging') }}