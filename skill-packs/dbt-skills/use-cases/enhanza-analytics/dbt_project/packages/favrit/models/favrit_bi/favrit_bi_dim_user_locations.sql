{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

-- Columns enumerated by scripts/expand_star_models.py from the upstream's own
-- declaration; `select *` gave this model no column contract. Regenerate after
-- changing the upstream contract; do not hand-edit the list.
select
  
    UserLocationId
    , Name
    , Address
    , ZipCode
    , City
    , Country
    , Phone
    , Email
    , IsActive
    , CreatedAt
    , UpdatedAt
from {{ ref('favrit_bi_dim_user_locations_staging') }}
