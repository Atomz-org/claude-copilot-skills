{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}


select
  o.OrgId
  , cs.OrgName
  , p.ProjectNumber
  , p.Description Project
  , o.* except (OrgId, CustomerId, ProjectId)
  , c.Name as CustomerName
  , c.CustomerNumber
  , c.OrganisationNumber
  , c.City as CustomerCity
  , c.Country as CustomerCountry
from {{ ref('fortnox_bi_fact_offers_staging') }} o
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs 
    on o.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c 
    on o.CustomerId = c.CustomerId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p 
    on o.ProjectId = p.ProjectId
where
  o.OfferDate between date_sub(current_date(), interval 3 year)
  and date_add(current_date(), interval 1 year)