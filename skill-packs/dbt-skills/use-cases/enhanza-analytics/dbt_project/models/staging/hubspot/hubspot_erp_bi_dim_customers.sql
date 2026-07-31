{{ config(materialized='ephemeral', enabled = var('is_hubspot_enabled', false)) }}

-- Adapts HubSpot to the common unified schema so erp_bi_dim_customers can union it.
--
-- SOURCE IS HubSpot *companies*, NOT contacts. This dimension is organisation-shaped —
-- OrganisationNumber, VATNumber, TermsOfPayment. HubSpot contacts are people; they do not
-- fit it and have no home in the unified layer. Do not "fix" this by unioning contacts in.
--
-- Column list, order, and count are copied from fortnox_erp_bi_dim_customers.sql — 44
-- columns before add_erp_fields(). union_queries() emits a positional UNION ALL, so a
-- column out of position with a compatible type unions cleanly and transposes the data.
-- Diff this against fortnox_erp_bi_dim_customers.sql before merging.
--
-- HubSpot is a CRM, so it supplies roughly a quarter of an ERP customer schema and the rest
-- is typed NULL — the same shape as shopify_erp_bi_dim_customers.sql, more so. Notably
-- absent: everything invoice-related (HubSpot has no ledger), all delivery fields (no
-- fulfilment), and OrganisationNumber (no native org-number property).
--
-- [NEEDS INPUT] no hubspot_api_<uid> dataset exists yet. Every column read from the staging
-- model below is a specification for the ingestion job, not an observed schema. The staging
-- model is still a stub; this adapter cannot compile until it enumerates these columns.
--
-- [NEEDS INPUT] type-verify against Fortnox before the first union build. Fortnox's staging
-- model passes several columns through raw from the API, so the true type is not readable
-- from its SQL: DefaultTemplate, DefaultVATType, DefaultDeliveryType, TermsOfPayment,
-- EmailInvoice, InvoiceDiscount, isActive. A string-vs-bool mismatch fails the union
-- loudly, which is the safe direction; numeric-vs-numeric coerces silently and is fine.

select
  c.CustomerId
  , c.CustomerNumber
  , c.Name
  , cast(null as string) OrganisationNumber   -- no native HubSpot property; often a custom field [NEEDS INPUT]
  , c.Address
  , c.ZipCode
  , c.Phone
  , cast(null as string) AdditionalPhone
  , cast(null as string) Email                -- HubSpot companies carry `domain`, not an email; see Website
  , c.Website                                 -- from the company `domain` property
  , cast(null as string) Fax
  , c.City
  , c.Type                                    -- from `lifecyclestage`, the closest analogue to Upsales' journeyStep
  , c.isActive                                -- [NEEDS INPUT] derive from archived/deleted state; type must match Fortnox
  , c.Country
  , cast(null as string) Comments
  , c.OurReference                            -- from the company owner's name
  , cast(null as string) YourReference
  , cast(null as string) DefaultTemplate
  , cast(null as string) DefaultVATType
  , cast(null as string) TemplateReference
  , cast(null as string) DefaultDeliveryType
  -- HubSpot has no fulfilment concept; every delivery field is NULL rather than mirrored
  -- from the postal address, because a CRM address is not a ship-to address.
  , cast(null as string) DeliveryCountry
  , cast(null as string) DeliveryCity
  , cast(null as string) DeliveryAddress1
  , cast(null as string) DeliveryAddress2
  , cast(null as string) DeliveryName
  , cast(null as string) DeliveryPhone1
  , cast(null as string) DeliveryPhone2
  , cast(null as string) DeliveryZipCode
  , cast(null as string) DeliveryFax
  , cast(null as string) VisitingAddress
  , cast(null as string) VisitingCity
  , cast(null as string) VisitingCountry
  , cast(null as string) TermsOfPayment
  , cast(null as string) EmailInvoice
  , cast(null as string) InvoiceRemark
  , cast(null as string) VATNumber
  , cast(null as string) PriceListId
  , cast(null as string) CostCenterId
  , cast(null as string) ProjectId
  -- HubSpot has no invoices. Deal close dates are NOT a substitute: a closed-won deal is
  -- pipeline value, not booked revenue, and populating these from deals would put a CRM
  -- number into a column every other connector fills from a ledger.
  , cast(null as date) FirstInvoiceDate
  , cast(null as date) LastInvoiceDate
  , cast(null as float64) InvoiceDiscount
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('hubspot_bi_dim_customers_staging') }} c
