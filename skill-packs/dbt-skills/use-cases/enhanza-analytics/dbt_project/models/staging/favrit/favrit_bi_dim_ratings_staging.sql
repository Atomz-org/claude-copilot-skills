{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  *
from {{ source('favrit_api', 'ratings') }} r
