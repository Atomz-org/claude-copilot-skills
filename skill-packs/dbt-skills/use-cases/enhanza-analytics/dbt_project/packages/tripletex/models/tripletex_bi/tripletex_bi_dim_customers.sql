{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  CustomerId
  ,  CustomerNumber
  , Name
  , OrganisationNumber
  , Address
  , ZipCode
  , Phone
  , AdditionalPhone
  , Email
  , Website
  , City
  , Type
  , isActive
  , Comments
  , OurReference
  , DefaultDeliveryType
  , DeliveryCity
  , DeliveryAddress1
  , DeliveryAddress2
  , DeliveryZipCode
  , TermsOfPayment
  , EmailInvoice
  , CostCenterId
  , InvoiceDiscount
from {{ ref('tripletex_bi_dim_customers_staging') }}