{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with invoices as (
  select
    OrgId
    , cast({{ blank_to_null('customer') }} as string) CustomerNumber
    , date(min(invoiceDate)) FirstInvoiceDate
    , date(max(invoiceDate)) LastInvoiceDate
  from {{ source('seventime_api', 'invoices') }}
  group by 1,2
)
, final as (
  select
    c.OrgId || "-" || c._id CustomerId
    , c.customerNumber CustomerNumber
    , trim(replace(initcap(c.name)," Ab"," AB")) Name
    , c.organizationNumber OrganisationNumber
    , {{ blank_to_null('c.address') }} Address
    , {{ blank_to_null('c.zipCode') }} ZipCode
    , {{ blank_to_null('c.phone') }} Phone
    , cast(null as STRING) as AdditionalPhone
    , {{ blank_to_null('c.email') }} Email
    , cast(null as STRING) as Website
    , cast(null as STRING) as Fax
    , initcap({{ blank_to_null('c.city') }}) City
    , cast(null as STRING) as Type
    , c.isActive as isActive
    , cc.CountryName Country
    , {{ blank_to_null('c.notes') }} Comments
    , cast(null as STRING) as OurReference
    , cast(null as STRING) as YourReference
    , cast(null as STRING) as DefaultTemplate
    , cast(null as STRING) as DefaultVATType
    , cast(null as STRING) as TemplateReference
    , cast(null as STRING) as DefaultDeliveryType
    , cast(null as STRING) as DeliveryCountry
    , cast(null as STRING) as DeliveryCity
    , cast(null as STRING) as DeliveryAddress1
    , cast(null as STRING) as DeliveryAddress2
    , cast(null as STRING) as DeliveryName
    , cast(null as STRING) as DeliveryPhone1
    , cast(null as STRING) as DeliveryPhone2
    , cast(null as STRING) as DeliveryZipCode
    , cast(null as STRING) as DeliveryFax
    , cast(null as STRING) as VisitingAddress
    , cast(null as STRING) as VisitingCity
    , cast(null as STRING) as VisitingCountry
    , initcap(billingMethod) TermsOfPayment
    , cast(null as STRING) as EmailInvoice
    , cast(null as STRING) as InvoiceRemark
    , cast(null as STRING) as VATNumber
    , cast(null as STRING) as PriceListId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , i.FirstInvoiceDate
    , i.LastInvoiceDate
    , cast(null as FLOAT64) as InvoiceDiscount
  from {{ source('seventime_api', 'customers') }} c
  left join {{ source('public', 'country_codes') }} cc
    on cc.Alpha2Code=c.country
  left join invoices i
    on c.OrgId=i.OrgId
    and cast(c._id as string) = i.CustomerNumber
)
select *
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from final