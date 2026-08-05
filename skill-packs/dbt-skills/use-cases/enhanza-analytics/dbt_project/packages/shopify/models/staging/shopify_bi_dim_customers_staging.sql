{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Grain: one row per Shopify customer.
--
-- Quarantines shopify_api.customers: renaming, casting, and coercion happen here and
-- nowhere else. Nothing downstream references a raw Shopify column name.
--
-- Shopify has no organisation concept, so keys carry no OrgId prefix — `id` is already
-- unique within a shop. Cross-source uniqueness comes from the `-ds_shopify` suffix that
-- add_erp_fields() appends in the adapter, the same way Favrit does it.
--
-- [NEEDS INPUT] Column names assume the loader preserves Shopify REST Admin API field
-- names and lands `default_address` as a STRUCT. Verify against the landed schema before
-- the first build: a renamed column fails loudly at compile time, a re-typed one does not.

select
  cast(c.id as string) CustomerId
  , cast(c.id as string) CustomerNumber
  , trim({{ blank_to_null("concat(coalesce(c.first_name, ''), ' ', coalesce(c.last_name, ''))") }}) Name
  , trim({{ blank_to_null('c.default_address.company') }}) CompanyName
  , trim({{ blank_to_null('c.email') }}) Email
  , trim({{ blank_to_null('c.phone') }}) Phone
  , trim({{ blank_to_null('c.default_address.phone') }}) AdditionalPhone
  , trim({{ blank_to_null('c.default_address.address1') }}) Address
  , trim({{ blank_to_null('c.default_address.address2') }}) Address2
  , REGEXP_REPLACE({{ blank_to_null('c.default_address.zip') }}, ' ', '') ZipCode
  , initcap({{ blank_to_null('c.default_address.city') }}) City
  , trim({{ blank_to_null('c.default_address.province') }}) Province
  , initcap({{ blank_to_null('c.default_address.country') }}) Country
  , trim({{ blank_to_null('c.default_address.name') }}) DeliveryName
  , cast(c.state = 'enabled' as boolean) isActive
  , cast(c.verified_email as boolean) isVerifiedEmail
  , cast(c.tax_exempt as boolean) isTaxExempt
  , trim({{ blank_to_null('c.note') }}) Comments
  , trim({{ blank_to_null('c.tags') }}) Tags
  , cast(c.orders_count as int64) OrdersCount
  , cast(c.total_spent as float64) TotalSpent
  , trim({{ blank_to_null('c.currency') }}) Currency
  , cast(c.created_at as timestamp) CreatedAt
  , cast(c.updated_at as timestamp) UpdatedAt
from {{ source('shopify_api', 'customers') }} c
