{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'seventime', 'upsales', 'visma_eaccounting', 'visma_economic'])
) }}

{% set cxm_cols = ['ArticleId'] %}

select
  ArticleIdERP ArticleId
  , case
    when ArticleNumber is null and ArticleName is null
      then "Unknown"
    when ArticleName is null
      then ArticleNumber
    when ArticleNumber is null
       then ArticleName
    else ArticleName || " (" || ArticleNumber || ")"
    end ArticleName
  , ArticleNumber
  , PurchasePrice ArticlePurchasePrice
  , {{ blank_to_null('Manufacturer') }} as Manufacturer
  , d0.DataSource
  , d0.Active as isActive
  {{ cxm_select(cxm_cols) }}
from {{ ref('erp_bi_dim_articles') }} d0
{% if var('is_fortnox_enabled') %}
{{ cxm_left_join(model_alias("dim_articles"), cxm_cols) }}
{% endif %}
order by 1