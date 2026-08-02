{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  SupplierNumber
  , OrganisationNumber
  , Name
  , Address1
  , Address2
  , ZipCode
  , City
  , CountryCode
  , Country
  , Phone
  , Email
  , Active as isActive
  , TermsOfPayment
  , PreDefinedAccount
  , Currency
  , SupplierId
  , CostCenterId
  , ProjectId
  , FirstInvoiceDate
  , {{ add_erp_fields(columns=['SupplierId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_dim_suppliers_staging') }}