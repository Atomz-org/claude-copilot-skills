{{ config(materialized='ephemeral', enabled = var('is_hubspot_enabled', false)) }}

-- Adapts HubSpot to the common unified schema so erp_bi_dim_customers can union it.
-- The output columns must match every other source's dim_customers adapter exactly, in the
-- same order. A missing column fails the UNION ALL at compile time, which is loud; a
-- column in the wrong position with a compatible type does not fail at all — it silently
-- transposes the data. Diff this against fortnox_erp_bi_dim_customers.sql before merging.
-- [NEEDS INPUT] replace the column list

select
    -- ColumnName
    *
from {{ ref('hubspot_bi_dim_customers_staging') }}
