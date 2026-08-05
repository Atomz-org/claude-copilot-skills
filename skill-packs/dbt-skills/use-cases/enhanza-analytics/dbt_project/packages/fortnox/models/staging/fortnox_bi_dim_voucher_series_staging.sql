{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || Year || '-' || {{ blank_to_null('Code') }} as VoucherSeriesId,
  Code,
  Description,
  Manual as isManual
from
  {{ source('fortnox_api', 'voucher_series') }}
