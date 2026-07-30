{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || ArticleNumber BundleArticleId
  , {{ blank_to_null ("json_extract_scalar(Bundle, '$.Comment')") }} Note
  , json_extract_scalar(Bundle, '$.PriceAdjustmentRow.ConstructionAccount') ConstructionAccount
  , json_extract_scalar(Bundle, '$.PriceAdjustmentRow.EuAccount') EuAccount
  , json_extract_scalar(Bundle, '$.PriceAdjustmentRow.EuVatAccount') EuVatAccount
  , json_extract_scalar(Bundle, '$.PriceAdjustmentRow.ExportAccount') ExportAccount
  , json_extract_scalar(Bundle, '$.PriceAdjustmentRow.SalesAccount') SalesAccount
  , cast(json_extract_scalar(Bundle, '$.PriceAdjustmentRow.Vat') as float64) VAT
  , OrgId || '-' || json_extract_scalar(r, '$.ArticleNumber') ArticleId
  , cast(json_extract_scalar(r, '$.FixedPrice') as boolean) isFixedPrice
  , cast(json_extract_scalar(r, '$.Quantity') as int64) QuantityInBundle
from {{ source('fortnox_api', 'articles') }} a
, unnest(json_extract_array(a.Bundle, '$.SubItems')) r
where BundleArticle is TRUE