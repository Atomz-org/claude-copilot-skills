{{ config(
    alias=model_alias(model.name),
    enabled = var('is_hubspot_enabled', false) and var('is_hubspot_contacts_enabled', false)
) }}

-- Quarantines the raw HubSpot source: rename, cast, and coerce here and nowhere else.
-- Nothing downstream may reference a raw column name.
-- Enumerate every column — `select *` must not survive past this layer.
--
-- PERSONAL DATA. This table carries identifiable individuals — prospects and form-fills,
-- not customers of record. Rule 17 requires masking, hashing, or exclusion to happen HERE,
-- in staging, before anything downstream reads it. `select *` is the opposite of that: it
-- forwards every raw property, including email, phone, and address, to whatever reads the
-- model next.
--
-- It stays `select *` rather than becoming an allowlist because no `hubspot_api_<uid>`
-- dataset exists yet, so an enumerated list would be invented column names (rule 5) — and
-- an invented allowlist is worse than none, because it reads as a completed PII review.
--
-- Two things therefore hold the exposure instead, and both are structural:
--   1. `is_hubspot_contacts_enabled` gates this model on its own, so enabling the HubSpot
--      package does not enable it. Both flags are required.
--   2. No `erp_bi_dim_contacts` union model exists, so nothing in the unified layer reads
--      this and the connector claims no contacts concept in ontology/connectors.yml.
--
-- [NEEDS INPUT] the data-protection owner has not ruled on the remediation for each PII
-- column. When they do, replace the star with the allowlist that applies it — direct
-- identifiers (email, phone) and quasi-identifiers (address) each named with the decision
-- taken — and record the facets in ontology/annotations.yml so the PII tag reaches
-- Lightdash, Wren, and the catalog. Only then flip the flag.

select
    -- RawColumnName as ColumnName
    *
from {{ source('hubspot_api', 'contacts') }}
