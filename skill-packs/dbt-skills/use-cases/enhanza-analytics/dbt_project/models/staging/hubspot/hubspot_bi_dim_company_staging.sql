{{ config(alias=model_alias(model.name), enabled = var('is_hubspot_enabled', false)) }}

-- Quarantines the raw HubSpot source: rename, cast, and coerce here and nowhere else.
-- Nothing downstream may reference a raw column name.
-- Enumerate every column — `select *` must not survive past this layer.
-- [NEEDS INPUT] replace the column list with the real one from hubspot_api.account_details

select
    -- RawColumnName as ColumnName
    *
from {{ source('hubspot_api', 'account_details') }}
