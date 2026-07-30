{{ config(materialized='view') }}

select
    1001 as order_id,
    501 as customer_id,
    125.50 as order_amount,
    'paid' as order_status,
    current_date as order_date
