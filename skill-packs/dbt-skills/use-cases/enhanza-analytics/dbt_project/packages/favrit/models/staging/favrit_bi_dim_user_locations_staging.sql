{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  cast(f.id as string) UserLocationId
  , trim({{ blank_to_null('f.name') }}) Name
  , trim({{ blank_to_null('f.address') }}) Address
  , trim({{ blank_to_null('f.postal_code') }}) ZipCode
  , trim({{ blank_to_null('f.city') }}) City
  , trim({{ blank_to_null('f.country') }}) Country
  , trim({{ blank_to_null('f.phone') }}) Phone
  , trim({{ blank_to_null('f.email') }}) Email
  , f.is_active as IsActive
  , {{ blank_to_null('f.created_at') }} CreatedAt
  , {{ blank_to_null('f.updated_at') }} UpdatedAt
from {{ source('favrit_api', 'user_location') }} f
