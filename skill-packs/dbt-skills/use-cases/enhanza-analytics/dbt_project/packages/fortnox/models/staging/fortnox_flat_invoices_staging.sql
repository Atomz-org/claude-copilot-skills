{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}


select
  i.OrgId,
  cs.OrgName,
  p.ProjectNumber,
  p.Description Project,
  i.*
except
  (OrgId, customerId, FinancialYearId),
  c.Name as CustomerName,
  c.CustomerNumber,
  c.OrganisationNumber,
  c.City as CustomerCity,
  c.Country as CustomerCountry,
  c.FirstInvoiceDate as CustomerFirstInvoiceDate,
  c.LastInvoiceDate as CustomerLastInvoiceDate
from
  {{ ref('fortnox_bi_fact_invoices_staging') }} i
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs ON i.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c ON i.CustomerId = c.CustomerId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p ON i.ProjectId = p.ProjectId
where
  i.InvoiceDate between date_sub(current_date(), interval 3 year)
  AND date_add(current_date(), interval 1 year)