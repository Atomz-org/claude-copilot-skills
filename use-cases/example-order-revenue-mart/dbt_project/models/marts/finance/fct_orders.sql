-- Two config values are computed rather than hardcoded, both for portability:
--
--   incremental_strategy  DuckDB and Postgres have no merge strategy. The failure shows
--                         up on the SECOND run only — the first is a plain create that
--                         never exercises the strategy — so a hardcoded 'merge' is a
--                         portability bug with a one-run delay on it.
--
--   cluster/partition     Snowflake clusters, BigQuery partitions and clusters, DuckDB
--                         does neither. cluster_config() returns the right keys per
--                         adapter, or an empty dict where the concept does not exist.
--
-- Note there are no comments inside the config() call below: `--` is SQL, not Jinja, so
-- inside a Jinja expression it is a syntax error rather than a comment. For the same
-- reason this comment does not spell out Jinja's delimiters — Jinja renders SQL comments
-- too, so a tag written here would be evaluated.

{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy=incremental_upsert_strategy(),
        on_schema_change='append_new_columns',
        **cluster_config(['ordered_date'])
    )
}}

with

orders as (
    select * from {{ ref('int_orders_with_line_totals') }}

    {% if is_incremental() %}
    -- 3-day lookback. Measured p99 arrival lag is 38h (use-case spec section 4);
    -- the window is p99 x 2. Anchored to max() in `this`, NOT current_date — a
    -- skipped run must not leave a permanent hole.
    where ordered_at >= (
        select {{ dbt.dateadd('day', -3, 'max(ordered_at)') }} from {{ this }}
    )
    {% endif %}
),

customers as (
    select * from {{ ref('dim_customers') }}
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        customers.region,
        orders.order_status,
        orders.line_item_count,
        orders.order_amount                                as order_amount_usd,

        -- Cast the subtraction: DECIMAL(28,6) - DECIMAL(28,6) widens to DECIMAL(38,6),
        -- which does not match the contract's numeric(28,6).
        cast(orders.gross_line_amount - orders.discount_amount as {{ money_type() }})
                                                           as net_line_amount_usd,
        orders.ordered_at,
        cast(orders.ordered_at as date)                    as ordered_date

    -- left join: guest checkouts have no customer_id (~3% of orders) and must not be
    -- dropped from revenue. `region` is null for those rows, which is expected.
    from orders
    left join customers on orders.customer_id = customers.customer_id
)

select * from final
