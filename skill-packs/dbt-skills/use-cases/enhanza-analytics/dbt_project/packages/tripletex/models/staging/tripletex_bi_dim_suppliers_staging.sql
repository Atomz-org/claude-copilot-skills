{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  cast(s.supplierNumber as string) SupplierNumber
  , trim({{ blank_to_null('s.organizationNumber') }}) OrganisationNumber
  , trim(s.name) Name
  , trim({{ blank_to_null('a.addressLine1') }}) Address1
  , trim({{ blank_to_null('a.addressLine2') }}) Address2
  , trim({{ blank_to_null('a.postalCode') }}) ZipCode
  , initcap(trim({{ blank_to_null('a.city') }})) City
  , trim({{ blank_to_null('s.phoneNumber') }}) Phone
  , trim({{ blank_to_null('s.email') }}) Email
  , not s.isInactive as isActive
  , acc.number PreDefinedAccount
  , c.code Currency
  , s.OrgId || '-' || s.id SupplierId
from {{ source('tripletex_api', 'supplier') }} s
left join {{ source('tripletex_api', 'address') }} a
  on s.OrgId = a.OrgId
  and json_extract_scalar(s.postalAddress, '$.id') = cast(a.id as string)
left join {{ source('tripletex_api', 'account') }} acc
  on acc.OrgId = s.OrgId
  and cast(acc.id as string) = json_extract_scalar(s.ledgerAccount, '$.id')
left join {{ source('tripletex_api', 'currency') }} c
  on c.OrgId = s.OrgId
  and cast(c.id as string) = json_extract_scalar(s.currency, '$.id')