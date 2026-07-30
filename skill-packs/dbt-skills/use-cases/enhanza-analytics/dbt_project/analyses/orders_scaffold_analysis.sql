select
    order_id,
    customer_id,
    order_amount
from {{ ref('orders_mart_scaffold') }}
order by order_id
