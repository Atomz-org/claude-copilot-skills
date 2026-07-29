{{ config(materialized='ephemeral') }}

with

orders as (
    select * from {{ ref('stg_shopify__orders') }}
),

line_items as (
    select * from {{ ref('stg_shopify__order_lines') }}
),

line_totals as (
    -- Collapse N lines to 1 row per order BEFORE the join, so the order grain survives.
    -- Summing across the fanned-out join instead would inflate every total.
    select
        order_id,

        -- Explicit casts, not decoration. count(*) is BIGINT on DuckDB, INT64 on
        -- BigQuery and NUMBER(38,0) on Snowflake; sum() over DECIMAL(28,6) widens to
        -- DECIMAL(38,6) everywhere. fct_orders carries an enforced contract that
        -- compares exact warehouse types, so an uncast aggregate fails the build on
        -- whichever adapter you did not develop on.
        cast(count(*) as {{ dbt.type_int() }})             as line_item_count,
        cast(sum(line_amount) as {{ money_type() }})       as gross_line_amount,
        cast(sum(discount_amount) as {{ money_type() }})   as discount_amount
    from line_items
    group by 1
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        orders.ordered_at,
        orders.order_amount,

        -- A refund overrides any fulfillment state. Every status is mapped
        -- explicitly; anything unrecognised — including null — becomes 'unknown'.
        --
        -- Deliberately NOT a pass-through `else orders.payment_status`. Passing an
        -- unmapped value straight into the mart makes the closed-domain contract a
        -- lie, and a new Shopify enum value would turn every downstream build red.
        -- Collapsing to 'unknown' keeps the domain closed; the warn-severity test in
        -- _int_finance__models.yml is what tells you a new value has appeared.
        case
            when orders.payment_status = 'refunded'  then 'refunded'
            when orders.payment_status = 'cancelled' then 'cancelled'
            when orders.payment_status = 'fulfilled' then 'fulfilled'
            when orders.payment_status = 'paid'      then 'paid'
            when orders.payment_status = 'pending'   then 'pending'
            else 'unknown'
        end                                        as order_status,

        coalesce(line_totals.line_item_count, 0)   as line_item_count,
        coalesce(line_totals.gross_line_amount, 0) as gross_line_amount,
        coalesce(line_totals.discount_amount, 0)   as discount_amount

    from orders
    left join line_totals on orders.order_id = line_totals.order_id
    where not orders.is_test_order
)

select * from final
