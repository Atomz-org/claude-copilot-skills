{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  i.OrgId,
  cs.OrgName,
  i.*
except(
    OrgId,
    SupplierInvoiceId,
    SupplierId,
    ProjectId,
    CostCenterID
  ),
  s.Name as SupplierName,
  a.Description as ArticleName,
  cc.Description as CostCenter,
  p.Description as Project,
from
  {{ ref('fortnox_bi_fact_supplier_invoice_rows_staging') }} i
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs ON i.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_suppliers_staging') }} s on i.SupplierId = s.SupplierId
  left join {{ ref('fortnox_bi_dim_articles_staging') }} a ON i.ArticleId = a.ArticleId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on i.CostCenterId = cc.CostCenterId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p on i.ProjectId = p.ProjectId