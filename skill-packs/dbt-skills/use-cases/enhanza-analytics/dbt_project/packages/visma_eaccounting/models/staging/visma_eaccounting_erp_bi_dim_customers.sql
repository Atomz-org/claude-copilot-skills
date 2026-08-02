{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with invoices as (
  select
    OrgId
    , cast({{ blank_to_null('CustomerId') }} as string) CustomerNumber
    , date(min(InvoiceDate)) FirstInvoiceDate
    , date(max(InvoiceDate)) LastInvoiceDate
  from {{ source('visma_eaccounting_api', 'customerinvoices') }}
  group by 1,2
)
, final as (
  select
    c.OrgId || '-' || c.Id as CustomerId
    , c.CustomerNumber
    , trim(replace(initcap(c.Name), " Ab", " AB")) as Name
    --what is CorporateIdentityNumber and could it be used instead of OrganisationNumber below?
    , c.CorporateIdentityNumber as OrganisationNumber
    , c.InvoiceAddress1 as Address
    , if(c.InvoicePostalCode = "", null, REGEXP_REPLACE(c.InvoicePostalCode, ' ', '')) as ZipCode
    , coalesce({{ blank_to_null('c.Telephone') }}, {{ blank_to_null('c.ContactPersonPhone') }}, {{ blank_to_null('c.ContactPersonMobile') }}) as Phone
    , cast(null as STRING) as AdditionalPhone
    , {{ blank_to_null('c.EmailAddress') }} as Email
    , cast(null as STRING) as Website
    , cast(null as STRING) as Fax
    , initcap({{ blank_to_null('c.InvoiceCity') }}) as City
    , if(c.IsPrivatePerson, 'Private', 'Company') as Type
    , isActive
    , initcap(cc.CountryName) as Country
    , {{ blank_to_null('c.Note') }} as Comments
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
    , json_extract_scalar(TermsOfPayment, '$.NameEnglish') TermsOfPayment
    , cast(null as STRING) as EmailInvoice
    , cast(null as STRING) as InvoiceRemark
    , cast(null as STRING) as VATNumber
    , cast(null as STRING) as PriceListId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , i.FirstInvoiceDate
    , i.LastInvoiceDate
    , DiscountPercentage as InvoiceDiscount
  from
    {{ source('visma_eaccounting_api', 'customers') }} c
  left join {{ source('public', 'country_codes') }} cc
    on cc.Alpha2Code=c.InvoiceCountryCode
  left join invoices i
    on c.OrgId = i.OrgId
    and cast(c.Id as string) = i.CustomerNumber
)
select *
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from final