{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Source-aligned Shopify customer dimension. Columns are enumerated rather than `select *`
-- so a new upstream Shopify field cannot appear here silently.
--
-- Uses an explicit config rather than {{ auto_config() }}: auto_config only sets `enabled`
-- for the erp_bi and logic_bi prefixes (global_configs('special_enabled_prefixes')), so a
-- shopify_bi model built through it would stay enabled while its staging model was gated
-- off, and fail on a disabled ref. This is the tripletex_bi and favrit_bi pattern.

select
  CustomerId
  , CustomerNumber
  , Name
  , CompanyName
  , Email
  , Phone
  , AdditionalPhone
  , Address
  , Address2
  , ZipCode
  , City
  , Province
  , Country
  , isActive
  , isVerifiedEmail
  , isTaxExempt
  , Comments
  , Tags
  , OrdersCount
  , TotalSpent
  , Currency
  , CreatedAt
  , UpdatedAt
from {{ ref('shopify_bi_dim_customers_staging') }}
