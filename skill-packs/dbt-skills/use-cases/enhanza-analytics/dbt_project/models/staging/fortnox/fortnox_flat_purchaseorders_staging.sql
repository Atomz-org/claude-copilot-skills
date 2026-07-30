{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  po.*
except(
    CustomerId,
    ArticleId,
    SupplierId,
    stockPointId,
    ProjectId,
    CostCenterId
  ),
  c.Name as Customer,
  a.Description as ArticleName,
  s.Name as Supplier,
  sp.Name as StockPoint,
  p.Description as Project,
  cc.Description as CostCenter
from
  {{ ref('fortnox_bi_fact_purchase_orders_staging') }} po
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c on c.CustomerId = po.CustomerId
  left join {{ ref('fortnox_bi_dim_articles_staging') }} a on a.ArticleId = po.ArticleId
  left join {{ ref('fortnox_bi_dim_suppliers_staging') }} s on s.SupplierId = po.SupplierId
  left join {{ ref('fortnox_bi_dim_stockpoints_staging') }} sp on sp.stockPointId = po.stockPointId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p on p.ProjectId = po.ProjectId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on cc.CostCenterId = po.CostCenterId