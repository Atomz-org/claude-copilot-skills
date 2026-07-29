with

source as (
    select * from {{ source('shopify', 'customers') }}
),

renamed as (
    select
        -- ids
        id                              as customer_id,

        -- strings
        email                           as customer_email,
        lower(trim(country_code))       as country_code,

        -- timestamps
        cast(created_at as timestamp)   as first_seen_at,

        -- metadata
        _fivetran_synced                as _loaded_at

    from source
    where not coalesce(_fivetran_deleted, false)
)

select * from renamed
