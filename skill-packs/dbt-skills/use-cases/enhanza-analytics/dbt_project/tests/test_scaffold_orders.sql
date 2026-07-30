select
    order_id
from {{ ref('orders_mart_scaffold') }}
where order_id is null
