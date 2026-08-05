{{ config(enabled = var('is_demopos_enabled', false)) }}

with

source as (
    select * from {{ source('demopos', 'customers') }}
),

renamed as (
    select
        -- ids
        customer_ref                     as customer_id,

        -- strings
        email_address                    as customer_email,
        lower(trim(country))             as country_code,

        -- timestamps
        cast(signed_up_at as timestamp)  as first_seen_at,

        -- metadata
        exported_at                      as _loaded_at

    from source
    -- Unlike the Fivetran-landed shopify source there is no soft-delete flag to filter:
    -- the till exports a full snapshot nightly, so a deleted customer simply stops
    -- appearing in the next export.
)

select * from renamed
