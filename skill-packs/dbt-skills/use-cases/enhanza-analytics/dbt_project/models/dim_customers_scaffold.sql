{{ config(materialized='view') }}

select
    distinct customer_id
from {{ ref('stg_sales_orders_scaffold') }}
