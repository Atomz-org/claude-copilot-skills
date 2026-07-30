select
    order_id
from {{ ref('orders_mart') }}
where order_id is null
