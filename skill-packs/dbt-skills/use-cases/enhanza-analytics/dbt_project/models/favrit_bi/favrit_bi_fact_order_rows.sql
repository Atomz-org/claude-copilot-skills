{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  *
from {{ ref('favrit_erp_bi_fact_order_rows') }}
