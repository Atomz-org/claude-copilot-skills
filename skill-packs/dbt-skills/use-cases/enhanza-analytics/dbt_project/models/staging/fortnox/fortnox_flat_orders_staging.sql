{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}


select
  i.OrgId,
  cs.OrgName,
  i.* except(OrgId, CustomerId),
  c.Name as CustomerName,
  c.CustomerNumber,
  c.City as CustomerCity,
  c.Country as CustomerCountry,
from
  {{ ref('fortnox_bi_fact_orders_staging') }} i
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs ON i.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c ON i.CustomerId = c.CustomerId
where
  i.OrderDate between date_sub(current_date(), interval 3 year)
  AND date_add(current_date(), interval 1 year)