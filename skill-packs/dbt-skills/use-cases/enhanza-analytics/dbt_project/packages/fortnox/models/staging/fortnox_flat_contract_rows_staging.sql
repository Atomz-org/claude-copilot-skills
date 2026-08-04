{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  i.OrgId
  , cs.OrgName
  , i.*
except(
    OrgId
    , CustomerId
    , ArticleId
    , CostCenterId
    , ProjectId)
  , a.Description ArticleName
  , c.Name CustomerName
  , c.CustomerNumber
  , c.City CustomerCity
  , c.Country CustomerCountry
  , c.FirstInvoiceDate CustomerFirstInvoiceDate
  , c.LastInvoiceDate CustomerLastInvoiceDate
  , cc.Description CostCenter
  , cc.Code CostCenterNumber
  , p.Description Project
  , p.ProjectNumber
from {{ ref('fortnox_bi_fact_contract_rows_staging') }} i
left join {{ ref('fortnox_bi_dim_company_staging') }} cs
    on i.OrgId = cs.OrgId
left join {{ ref('fortnox_bi_dim_customers_staging') }} c
    on i.CustomerId = c.CustomerId
left join {{ ref('fortnox_bi_dim_articles_staging') }} a
    on i.ArticleId = a.ArticleId
left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc
    on i.CostCenterId = cc.CostCenterId
left join {{ ref('fortnox_bi_dim_projects_staging') }} p
    on i.ProjectId = p.ProjectId