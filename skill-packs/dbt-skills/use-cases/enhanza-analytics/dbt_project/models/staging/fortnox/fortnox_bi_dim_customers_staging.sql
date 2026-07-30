{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with invoices as (
  select
    OrgId
    , {{ blank_to_null('CustomerNumber') }} CustomerNumber
    , date(min(InvoiceDate)) FirstInvoiceDate
    , date(max(InvoiceDate)) LastInvoiceDate
  from {{ ref('fortnox_base_v2_invoices') }}
  group by 1,2
)

select
  c.OrgId || '-' || {{ blank_to_null('c.CustomerNumber') }} CustomerId
  , c.CustomerNumber
  , trim(c.Name) Name
  , {{ blank_to_null('c.OrganisationNumber') }} OrganisationNumber
  , c.Address1 Address
  , REGEXP_REPLACE({{blank_to_null('c.ZipCode')}}, ' ', '') ZipCode
  , c.Phone1 Phone
  , c.Phone2 AdditionalPhone
  , c.Email
  , trim({{ blank_to_null('c.WWW') }}) Website
  , trim({{ blank_to_null('c.Fax') }}) Fax
  , initcap({{ blank_to_null('c.City') }}) City
  , initcap(c.Type) Type
  , Active isActive
  , initcap(c.Country) Country
  , {{ blank_to_null('c.Comments') }} Comments
  , {{ blank_to_null('c.OurReference') }} OurReference
  , {{ blank_to_null('c.YourReference') }} YourReference
  , c.DefaultTemplates.Invoice DefaultTemplate
  , trim({{ blank_to_null('c.VATType') }}) DefaultVATType
  , c.Address2 TemplateReference
  , c.DefaultDeliveryTypes.Invoice DefaultDeliveryType
  , trim({{ blank_to_null('c.DeliveryCountry') }}) DeliveryCountry
  , trim({{ blank_to_null('c.DeliveryCity') }}) DeliveryCity
  , trim({{ blank_to_null('c.DeliveryAddress1') }}) DeliveryAddress1
  , trim({{ blank_to_null('c.DeliveryAddress2') }}) DeliveryAddress2
  , trim({{ blank_to_null('c.DeliveryName') }}) DeliveryName
  , trim({{ blank_to_null('c.DeliveryPhone1') }}) DeliveryPhone1
  , trim({{ blank_to_null('c.DeliveryPhone2') }}) DeliveryPhone2
  , trim({{ blank_to_null('c.DeliveryZipCode') }}) DeliveryZipCode
  , trim({{ blank_to_null('c.DeliveryFax') }}) DeliveryFax
  , trim({{ blank_to_null('c.VisitingAddress') }}) VisitingAddress
  , trim({{ blank_to_null('c.VisitingCity') }}) VisitingCity
  , trim({{ blank_to_null('c.VisitingCountry') }}) VisitingCountry
  , c.TermsOfPayment
  , c.EmailInvoice
  , trim({{ blank_to_null('c.InvoiceRemark') }}) InvoiceRemark
  , {{ blank_to_null('c.VATNumber') }} VATNumber
  , c.OrgId || '-' || {{ blank_to_null('c.PriceList') }} PriceListId
  , c.OrgId || '-' || {{ blank_to_null('c.CostCenter') }} CostCenterId
  , c.OrgId || '-' || {{ blank_to_null('c.Project') }} ProjectId
  , i.FirstInvoiceDate
  , i.LastInvoiceDate
  , c. InvoiceDiscount
from {{ source('fortnox_api', 'customers') }} c
left join invoices i
  on c.OrgId = i.OrgId
  and {{ blank_to_null('c.CustomerNumber') }} =  i.CustomerNumber
