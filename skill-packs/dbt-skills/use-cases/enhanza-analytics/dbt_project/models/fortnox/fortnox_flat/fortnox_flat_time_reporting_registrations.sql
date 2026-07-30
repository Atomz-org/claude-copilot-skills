{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
    c.OrgId
    , c.OrgName
    , bi.*
    except (OrgId, CostCenterId, CustomerId, ProjectId, ArticleId, UserId)
    , a.Description ArticleName
    , cstmr.Name as CustomerName
    , cstmr.CustomerNumber
    , cstmr.City as CustomerCity
    , cstmr.Country as CustomerCountry
    , cc.Code as CostCenterId
    , cc.Description as CostCenter
    , p.ProjectNumber as ProjectId
    , p.Description as Project
from {{ ref('fortnox_bi_time_reporting_registrations_staging') }} bi
    left join {{ ref('fortnox_bi_dim_company_staging') }} c on c.OrgId=bi.OrgId
    left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on cc.CostCenterId=bi.CostCenterId
    left join {{ ref('fortnox_bi_dim_projects_staging') }} p on p.ProjectId=bi.projectId
    left join {{ ref('fortnox_bi_dim_customers_staging') }} cstmr on cstmr.CustomerId = bi.CustomerId
    left join {{ ref('fortnox_bi_dim_articles_staging') }} a on a.ArticleId = bi.ArticleId