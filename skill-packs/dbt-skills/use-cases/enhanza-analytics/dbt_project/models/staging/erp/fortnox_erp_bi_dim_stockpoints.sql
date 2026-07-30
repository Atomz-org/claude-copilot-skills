{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  Code
  , Name
  , IdString
  , isActive
  , UsingCompanyAddress as isUsingCompanyAddress
  , DeliveryName
  , DeliveryAddress
  , DeliveryAddress2
  , DeliveryZipCode
  , DeliveryCity
  , DeliveryPhone
  , DeliveryCountryCode
  , StockPointId
  , {{ add_erp_fields(columns=['StockPointId']) }}
from {{ ref('fortnox_bi_dim_stockpoints_staging') }}
