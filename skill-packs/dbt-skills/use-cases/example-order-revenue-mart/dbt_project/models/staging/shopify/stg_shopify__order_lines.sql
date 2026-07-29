with

source as (
    select * from {{ source('shopify', 'order_lines') }}
),

renamed as (
    select
        -- ids
        id                                              as order_line_id,
        order_id,
        product_id,

        -- numerics
        quantity,
        cast(price as {{ dbt.type_numeric() }})         as line_amount,
        cast(discount as {{ dbt.type_numeric() }})      as discount_amount,

        -- metadata
        _fivetran_synced                                as _loaded_at

    from source
    where not coalesce(_fivetran_deleted, false)
)

select * from renamed
