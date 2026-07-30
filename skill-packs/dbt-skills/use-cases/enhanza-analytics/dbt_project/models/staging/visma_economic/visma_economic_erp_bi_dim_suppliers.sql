{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with main as (
  select
    cast(supplierNumber as string) SupplierNumber
    , cast(OrgId as string) OrganisationNumber
    , name Name
    , address Address1
    , cast(null as STRING) as Address2
    , if(zip is not null, regexp_replace(zip, ' ', ''), zip) ZipCode
    , initcap(city) City
    , cc.Alpha2Code CountryCode
    , cast(null as STRING) as Country
    , phone Phone
    , email Email
    , NOT s.barred as isActive
    , cast(null as STRING) as TermsOfPayment
    , cast(null as INT) as PreDefinedAccount
    , cast(null as STRING) as Currency
    , OrgId || '-' || if(supplierNumber = "", null, supplierNumber) SupplierId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , cast(null as DATE) as FirstInvoiceDate
  from
  {{ source('visma_economic_api', 'suppliers') }} s
  left join {{ source('public', 'country_codes') }} cc
    on lower(cc.CountryName)=lower(s.country)
)
select *
  , {{ add_erp_fields(columns=['SupplierId', 'CostCenterId', 'ProjectId']) }}
from main