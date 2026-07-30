{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  cast(o.id as string) OrderRowId
  , cast(o.order_id as string) OrderId
  , cast(o.product_id as string) ArticleId
  , cast(o.quantity as float64) OrderedQuantity
  , cast(o.delivered_quantity as float64) DeliveredQuantity
  , cast(o.unit_price as float64) Price
  , cast(o.discount_amount as float64) Discount
  , trim({{ blank_to_null('o.discount_type') }}) DiscountType
  , trim({{ blank_to_null('o.status') }}) OrderRowStatus
  , cast(o.vat_rate as float64) VAT
  , cast(o.customer_id as string) CustomerId
  , cast(o.account_id as string) AccountId
  , cast(o.cost_center_id as string) CostCenterId
  , cast(o.project_id as string) ProjectId
  , trim({{ blank_to_null('o.currency') }}) Currency
  , cast(o.created_at as timestamp) CreatedAt
  , cast(o.updated_at as timestamp) UpdatedAt
from {{ source('favrit_api', 'orderline') }} o
