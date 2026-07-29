{{ config(materialized='table') }}

with

customers as (
    select * from {{ ref('stg_shopify__customers') }}
),

final as (
    select
        customer_id,
        customer_email,
        country_code,

        -- Region mapping is business policy, owned by Finance Analytics. An unmapped
        -- country falls into 'OTHER' rather than null, so the accepted_values test
        -- catches a new market instead of a not_null test failing elsewhere.
        case
            when country_code in ('gb', 'fr', 'de', 'es', 'it', 'nl', 'se') then 'EMEA'
            when country_code in ('us', 'ca', 'mx')                         then 'AMER'
            else 'OTHER'
        end as region,

        first_seen_at

    from customers
)

select * from final
