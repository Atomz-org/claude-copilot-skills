{{ config(materialized='view') }}

select
    order_id,
    customer_id,
    order_amount
from {{ ref('stg_sales_orders_scaffold') }}
