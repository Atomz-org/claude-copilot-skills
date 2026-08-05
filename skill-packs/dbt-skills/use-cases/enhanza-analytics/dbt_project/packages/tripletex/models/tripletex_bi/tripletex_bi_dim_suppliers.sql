{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  SupplierNumber
  , OrganisationNumber
  , Name
  , Address1
  , Address2
  , ZipCode
  , City
  , Phone
  , Email
  , isActive
  , PreDefinedAccount
  , Currency
  , SupplierId
from {{ ref('tripletex_bi_dim_suppliers_staging') }}