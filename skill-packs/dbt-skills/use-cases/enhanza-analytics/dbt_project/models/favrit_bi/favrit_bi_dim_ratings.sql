{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  *
from {{ ref('favrit_bi_dim_ratings_staging') }}
