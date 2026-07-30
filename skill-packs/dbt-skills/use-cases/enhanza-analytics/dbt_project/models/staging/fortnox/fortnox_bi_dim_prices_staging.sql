{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  FromQuantity,
  Price,
  OrgId,
  OrgId || '-' || {{ blank_to_null('PriceList') }} as PriceListId,
  OrgId || '-' || {{ blank_to_null('ArticleNumber') }} as ArticleId,
from
  {{ source('fortnox_api', 'prices') }}
