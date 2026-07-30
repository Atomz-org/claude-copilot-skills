{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  Code,
  Name,
  Id as IdString,
  Active as isActive,
  UsingCompanyAddress,
  DeliveryName,
  DeliveryAddress,
  DeliveryAddress2,
  DeliveryZipCode,
  DeliveryCity,
  DeliveryPhone,
  DeliveryCountryCode,
  OrgId || '-' || {{ blank_to_null('Code') }} as StockPointId,
from
  {{ source('fortnox_api', 'stockpoints') }}
