{{ config(materialized='ephemeral', enabled = var('is_upsales_enabled', false)) }}

with orders as (
  select
    OrgId
    , json_extract_scalar(client, '$.id') CustomerNumber
    , date(min(date)) FirstInvoiceDate
    , date(max(date)) LastInvoiceDate
  from {{ source('upsales_api', 'orders') }}
  group by 1,2
)
, final as (
  select
    a.OrgId || '-' || a.id CustomerId
    , cast(a.id as string) CustomerNumber
    , trim(initcap(replace(a.name, " Ab", " AB"))) Name
    , a.orgNo OrganisationNumber
    , json_extract_scalar(a.addresses, '$[0].address') Address
    , json_extract_scalar(a.addresses, '$[0].zipcode') ZipCode
    , {{ blank_to_null('a.phone') }} Phone
    , cast(null as STRING) as AdditionalPhone
    , case
        when array_length(array(
          select value
          from unnest([webpage, facebook, twitter, linkedin]) value
          where value is not null)) > 1
          then array_to_string(array(
          select value
          from unnest([webpage, facebook, twitter, linkedin]) value
          where value is not null), '; ' )
        else null
      end Email --web pages used instead of email
    , cast(null as STRING) as Website
    , cast(null as STRING) as Fax
    , initcap(json_extract_scalar(a.addresses, '$[0].city')) City
    , initcap(a.journeyStep) Type
    , active as isActive
    , cc.CountryName Country
    , {{ blank_to_null('a.notes') }} Comments
    , json_extract_scalar(cast(json_extract_array(a.users) as array<json>)[safe_offset(0)], '$.name') OurReference
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
    , cast(null as STRING) as TermsOfPayment
    , cast(null as STRING) as EmailInvoice
    , cast(null as STRING) as InvoiceRemark
    , cast(null as STRING) as VATNumber
    , cast(null as STRING) as PriceListId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId

  -- , date(regDate) RegistrationDate
  -- , OrgId || '-' || json_extract_scalar(parent, '$.id') ParentAccountId
  -- , OrgId || '-' || json_extract_scalar(u, '$.id') UserId
  -- , json_extract_scalar(u, '$.email') UserEmail
  -- , OrgId || '-' || json_extract_scalar(p, '$.id') ProjectId
  -- , json_extract_scalar(p, '$.name') ProjectName
    , o.FirstInvoiceDate
    , o.LastInvoiceDate
    , cast(null as FLOAT64) as InvoiceDiscount
  from {{ source('upsales_api', 'accounts') }} a
    -- , unnest(cast(json_extract_array(projects) as array <json>)) p
  left join {{ source('public', 'country_codes') }} cc
    on cc.Alpha2Code=json_extract_scalar(a.addresses, '$[0].country')
  left join orders o
    on o.OrgId=a.OrgId
    and cast(a.id as string)=o.CustomerNumber
  where a.active is true
)
select *
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from final