{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  o.OrgId
  , cs.OrgName
  , p.ProjectNumber
  , p.Description Project
  , cc.Code CostCenterNumber
  , cc.Description CostCenter
  , o.* except (OrgId, CustomerId, ProjectId, CostCenterId)
  , c.Name as CustomerName
  , c.CustomerNumber
  , c.OrganisationNumber
  , c.City as CustomerCity
  , c.Country as CustomerCountry
from {{ ref('fortnox_bi_fact_contracts_staging') }} o
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs 
    on o.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c 
    on o.CustomerId = c.CustomerId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p 
    on o.ProjectId = p.ProjectId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc
    on o.CostCenterId = cc.CostCenterId