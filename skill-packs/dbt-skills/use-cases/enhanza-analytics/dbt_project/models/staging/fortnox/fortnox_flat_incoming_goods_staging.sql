{{ config(alias='fortnox_flat_incominggoods', enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  i.*
except(
    ArticleId,
    SupplierId,
    stockPointId,
    ProjectId,
    CostCenterId
  ),
  a.Description as ArticleName,
  s.Name as Supplier,
  sp.Name as StockPoint,
  p.Description as Project,
  cc.Description as CostCenter
from
  {{ ref('fortnox_bi_fact_incoming_goods_staging') }} i
  left join {{ ref('fortnox_bi_dim_articles_staging') }} a on a.ArticleId = i.ArticleId
  left join {{ ref('fortnox_bi_dim_suppliers_staging') }} s on s.SupplierId = i.SupplierId
  left join {{ ref('fortnox_bi_dim_stockpoints_staging') }} sp on sp.stockPointId = i.stockPointId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p on p.ProjectId = i.ProjectId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on cc.CostCenterId = i.CostCenterId