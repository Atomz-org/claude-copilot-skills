{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with invoices as (
  select
    cast({{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} as string) ArticleNumber
    , i.OrgId
    , date(i.InvoiceDate) InvoiceDate
  from {{ ref('fortnox_base_v2_invoices') }} i
  , unnest(json_extract_array(InvoiceRows)) r
)
select
  s.SupplierNumber
  , {{ blank_to_null('s.OrganisationNumber') }} OrganisationNumber
  , trim(s.Name) Name
  , {{ blank_to_null('s.Address1') }} Address1
  , s.Address2
  , {{ blank_to_null('s.ZipCode') }} ZipCode
  , initcap({{ blank_to_null('s.City') }}) City
  , s.CountryCode
  , cc.CountryName Country
  , {{ blank_to_null('s.Phone') }} Phone
  , {{ blank_to_null('s.Email') }} Email
  , s.Active
  , s.TermsOfPayment
  , safe_cast(s.PreDefinedAccount as int64) PreDefinedAccount
  , s.Currency
  , s.OrgId || '-' || {{ blank_to_null('s.SupplierNumber') }} SupplierId
  , s.OrgId || '-' || {{ blank_to_null('s.CostCenter') }} CostCenterId
  , s.OrgId || '-' || {{ blank_to_null('s.Project') }} ProjectId
  , date(min(i.InvoiceDate)) FirstInvoiceDate
from {{ source('fortnox_api', 'suppliers') }} s
left join {{ source('fortnox_api', 'articles') }} a
  on a.OrgId=s.OrgId
  and cast(a.SupplierNumber as string) = cast(s.SupplierNumber as string)
left join invoices i
  on i.OrgId=s.OrgId
  and cast({{ blank_to_null('a.ArticleNumber') }} as string) = i.ArticleNumber
left join {{ source('public', 'country_codes') }} cc
  on cc.Alpha2Code = s.CountryCode
group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18