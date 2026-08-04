{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name) ) }}

select
  id OpportunityNo
  , date(date) OpportunityDate
  , json_extract_scalar(user, '$.name') OurReference
  , currency Currency
  , currencyRate CurrencyRate
  --AccountNumber not available
  , cast(json_extract_scalar(r, '$.quantity') as float64) Quantity
  --Unit not available
  , cast(json_extract_scalar(r, '$.price') as float64) * cast(json_extract_scalar(r, '$.quantity') as float64) SalesValue
  , cast(json_extract_scalar(r, '$.purchaseCost') as float64) * cast(json_extract_scalar(r, '$.quantity') as float64) ContributionValue
  , json_extract_scalar(stage, '$.name') Stage
  , OrgId
  , OrgId || '-' || id OpportunityId
  , OrgId || '-' || json_extract_scalar(r, '$.product.id') ArticleId
  , OrgId || '-' || json_extract_scalar(client, '$.id') CustomerId
  , OrgId || '-' || extract(year from date) FinancialYearId
from {{ source('upsales_api', 'opportunities') }}
  , unnest(json_extract_array(orderRow)) r