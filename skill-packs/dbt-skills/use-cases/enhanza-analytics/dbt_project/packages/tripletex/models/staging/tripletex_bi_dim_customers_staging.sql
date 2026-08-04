{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  c.OrgId || '-' || c.id CustomerId
  , cast(c.customerNumber as string) CustomerNumber
  , trim({{ blank_to_null('c.name') }}) Name
  , trim({{ blank_to_null('c.organizationNumber') }}) OrganisationNumber
  , trim({{ blank_to_null('a.addressLine1') }}) Address
  , trim({{ blank_to_null('a.postalCode') }}) ZipCode
  , trim({{ blank_to_null('c.phoneNumber') }}) Phone
  , trim({{ blank_to_null('c.phoneNumberMobile') }}) AdditionalPhone
  , trim({{ blank_to_null('c.email') }}) Email
  , trim({{ blank_to_null('c.website') }}) Website
  , initcap(trim({{ blank_to_null('a.city') }})) City
  , case
    when c.isPrivateIndividual then 'Private'
    when length(c.organizationNumber)>0 then 'Company'
    else 'Undefined'
  end Type
  , not c.isInactive as isActive
  , trim({{ blank_to_null('c.description') }}) Comments
  , trim({{ blank_to_null('e.displayName') }}) OurReference
  , trim({{ blank_to_null('c.invoiceSendMethod') }}) DefaultDeliveryType
  , initcap(trim({{ blank_to_null('a_del.city') }})) DeliveryCity
  , trim({{ blank_to_null('a_del.addressLine1') }}) DeliveryAddress1
  , trim({{ blank_to_null('a_del.addressLine2') }}) DeliveryAddress2
  , trim({{ blank_to_null('a_del.postalCode') }}) DeliveryZipCode
  , cast(c.invoicesDueIn as string) TermsOfPayment
  , trim({{ blank_to_null('invoiceEmail') }}) EmailInvoice
  , c.OrgId || '-' || json_extract_scalar(c.department, '$.id') CostCenterId
  , discountPercentage as InvoiceDiscount
from {{ source('tripletex_api', 'customer') }} c
left join {{ source('tripletex_api', 'address') }} a
  on cast(a.id as string) = json_extract_scalar(c.postalAddress, '$.id')
  and a.OrgId = c.OrgId
left join {{ source('tripletex_api', 'address') }} a_del
  on cast(a_del.id as string) = json_extract_scalar(c.deliveryAddress, '$.id')
  and a_del.OrgId = c.OrgId
left join {{ source('tripletex_api', 'employee') }} e
  on cast(e.id as string) = json_extract_scalar(c.accountManager, '$.id')
  and a.OrgId = c.OrgId
where c.isCustomer is not FALSE
  -- some customers can also be suppliers, see isSupplier