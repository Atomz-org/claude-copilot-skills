{{ config(materialized='ephemeral', enabled = var('is_hubspot_enabled', false)) }}

-- Adapts the tenant's own HubSpot account to the common unified schema.
--
-- READ THIS BEFORE CHANGING THE SOURCE. `dim_company` holds ONE ROW PER TENANT — the
-- organisation whose warehouse this is. It is not a customer dimension. Every other
-- connector reads its own account record for this: upsales_api.self,
-- visma_eaccounting_api.companysettings.
--
-- The obvious-looking mapping "HubSpot companies -> dim_company" is WRONG. HubSpot
-- companies are customer organisations and belong in dim_customers (see
-- hubspot_erp_bi_dim_customers.sql). Sending them here would put every customer into a
-- dimension that downstream models assume has one row per tenant, and the failure would be
-- silent — the union would simply return more rows than anyone expects.
--
-- Contract is three columns before add_erp_fields(), matching
-- visma_eaccounting_erp_bi_dim_company.sql and upsales_erp_bi_dim_company.sql:
--   OrgId (cast to string), OrgName, City
--
-- [NEEDS INPUT] no hubspot_api_<uid> dataset exists yet, and `account_details` is the least
-- certain table in the set — several ingestion tools do not land HubSpot portal metadata at
-- all. If it is not available, drop 'dim_company' from the registry's included_models in
-- the same commit that deletes this model. A claim with no adapter is the xledger
-- fact_vouchers defect.

with main as (
  select
    OrgId
    , PortalName as OrgName        -- [NEEDS INPUT] confirm the landed column name
    , City                         -- [NEEDS INPUT] HubSpot portal metadata may not carry a city
  from {{ ref('hubspot_bi_dim_company_staging') }}
)
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main
