with

source as (
    select * from {{ source('shopify', 'orders') }}
),

renamed as (
    select
        -- ids
        id                                             as order_id,
        customer_id,

        -- strings
        lower(trim(financial_status))                  as payment_status,
        currency                                       as currency_code,

        -- numerics
        cast(total_price as {{ dbt.type_numeric() }})  as order_amount,

        -- booleans
        coalesce(test, false)                          as is_test_order,

        -- timestamps
        cast(created_at as timestamp)                  as ordered_at,

        -- metadata
        _fivetran_synced                               as _loaded_at

    from source
    where not coalesce(_fivetran_deleted, false)   -- soft deletes never leave staging
)

select * from renamed
