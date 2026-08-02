{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  i.OrgId,
  cs.OrgName,
  i.*
except(
    OrgId,
    Description,
    CustomerId,
    ArticleId,
    AccountId,
    CostCenterId,
    ProjectId
  ),
  if(
    i.ArticleNumber is null,
    i.Description,
    a.Description
  ) as ArticleName,
    a.PurchaseAccount,
    a.StockChangeAccount,
  c.Name as CustomerName,
  c.CustomerNumber,
  c.City as CustomerCity,
  c.Country as CustomerCountry,
  cc.Description as CostCenter,
  cc.Code as CostCenterId,
  p.Description as Project,
  p.ProjectNumber,
  a.PurchasePrice,
  a.SupplierName
from
  {{ ref('fortnox_bi_fact_order_rows_staging') }} i
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs ON i.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c ON i.CustomerId = c.CustomerId
  left join {{ ref('fortnox_bi_dim_articles_staging') }} a ON i.ArticleId = a.ArticleId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on i.CostCenterId = cc.CostCenterId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p on i.ProjectId = p.ProjectId