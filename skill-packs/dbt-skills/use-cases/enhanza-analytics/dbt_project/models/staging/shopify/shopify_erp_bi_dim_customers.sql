{{ config(materialized='ephemeral', enabled = var('is_shopify_enabled', false)) }}

-- Adapts Shopify to the common unified schema so erp_bi_dim_customers can union it.
-- Column list, order, and count are copied from fortnox_erp_bi_dim_customers.sql — 44
-- columns before add_erp_fields(). union_queries() emits a positional UNION ALL, so a
-- column out of position with a compatible type unions cleanly and transposes the data.
--
-- Shopify supplies about a third of the ERP customer schema; the rest is typed NULL. That
-- is expected for a non-ERP source and matches how Favrit pads fact_order_rows.
-- `default_address` serves as both the postal and the delivery address — Shopify keeps one
-- address per customer.
--
-- [NEEDS INPUT] type-verify against Fortnox before the first union build. These NULLs are
-- typed from the column's apparent Fortnox type, but Fortnox's staging model passes several
-- through raw from the API, so the true type is not readable from the SQL alone:
-- DefaultTemplate, DefaultVATType, DefaultDeliveryType, TermsOfPayment, EmailInvoice,
-- InvoiceDiscount. A string-vs-bool mismatch fails the union loudly; numeric-vs-numeric
-- coerces silently and is fine.

select
  c.CustomerId
  , c.CustomerNumber
  , c.Name
  , cast(null as string) OrganisationNumber
  , c.Address
  , c.ZipCode
  , c.Phone
  , c.AdditionalPhone
  , c.Email
  , cast(null as string) Website
  , cast(null as string) Fax
  , c.City
  , cast(null as string) Type
  , c.isActive
  , c.Country
  , c.Comments
  , cast(null as string) OurReference
  , cast(null as string) YourReference
  , cast(null as string) DefaultTemplate
  , cast(null as string) DefaultVATType
  , cast(null as string) TemplateReference
  , cast(null as string) DefaultDeliveryType
  , c.Country DeliveryCountry
  , c.City DeliveryCity
  , c.Address DeliveryAddress1
  , c.Address2 DeliveryAddress2
  , c.DeliveryName
  , c.AdditionalPhone DeliveryPhone1
  , cast(null as string) DeliveryPhone2
  , c.ZipCode DeliveryZipCode
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
  , cast(null as date) FirstInvoiceDate
  , cast(null as date) LastInvoiceDate
  , cast(null as float64) InvoiceDiscount
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('shopify_bi_dim_customers_staging') }} c
