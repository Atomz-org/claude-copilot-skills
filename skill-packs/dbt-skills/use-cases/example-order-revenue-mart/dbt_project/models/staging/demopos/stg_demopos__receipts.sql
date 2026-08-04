{{ config(enabled = var('is_demopos_enabled', false)) }}

with

source as (
    select * from {{ source('demopos', 'receipts') }}
),

renamed as (
    select
        -- ids
        receipt_ref                                     as receipt_id,
        customer_ref                                    as customer_id,
        register_id,

        -- strings
        lower(trim(status))                             as receipt_status,
        currency                                        as currency_code,

        -- numerics
        cast(total_amount as {{ dbt.type_numeric() }})  as receipt_amount,

        -- timestamps
        cast(sold_at as timestamp)                      as sold_at,

        -- metadata
        exported_at                                     as _loaded_at

    from source
)

select * from renamed
