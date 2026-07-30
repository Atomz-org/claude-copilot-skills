{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with cg as ( --customer groups endpoint is used instead of comments which are not available
  select
    OrgId || '-' || customerGroupNumber CustomerGroupId
    , name CustomerGroupName
  from {{ source('visma_economic_api', 'customer_groups') }}
)
, e as (
  select
    OrgId || '-' || employeeNumber EmployeeId
    , name OurReference
  from {{ source('visma_economic_api', 'employees') }}
)
, invoices as (
  select
    OrgId
    , json_extract_scalar(customer, '$.customerNumber') CustomerNumber
    , date(min(date)) FirstInvoiceDate
    , date(max(date)) LastInvoiceDate
  from {{ source('visma_economic_api', 'invoices_booked') }}
  group by 1,2
)
, final as (
  select
    c.OrgId || '-' || c.customerNumber CustomerId
    , cast(c.customerNumber as string) CustomerNumber
    , trim(replace(initcap(c.name), " Ab", " AB")) Name
    , cast(c.corporateIdentificationNumber as string) OrganisationNumber
    , c.address Address
    , if(c.zip = "", null ,regexp_replace(c.zip, ' ', '')) ZipCode
    , coalesce(c.mobilePhone, c.telephoneAndFaxNumber) Phone
    , cast(null as STRING) as AdditionalPhone
    , c.email Email
    , cast(null as STRING) as Website
    , cast(null as STRING) as Fax
    , initcap({{ blank_to_null('c.city') }}) City
    , if(c.ean is null, 'Private', 'Company') Type
    , NOT c.barred as isActive
    , initcap(c.country) Country
    , cg.CustomerGroupName Comments
    , e.OurReference
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
    , i.FirstInvoiceDate
    , i.LastInvoiceDate
    , cast(null as FLOAT64) as InvoiceDiscount
  from
    {{ source('visma_economic_api', 'customers') }} c
  left join cg
    on cg.CustomerGroupId=c.OrgId || '-' || json_extract_scalar(customerGroup, '$.customerGroupNumber')
  left join e
    on e.EmployeeId = OrgId || '-' || json_extract_scalar(salesPerson, '$.employeeNumber')
  left join invoices i
    on i.OrgId=c.OrgId
    and cast(c.customerNumber as string) = i.CustomerNumber
)
select *
  , {{ add_erp_fields(columns=['CustomerId', 'PriceListId', 'CostCenterId', 'ProjectId']) }}
from final