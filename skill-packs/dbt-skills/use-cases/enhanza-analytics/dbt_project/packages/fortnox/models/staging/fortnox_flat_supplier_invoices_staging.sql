{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

--one file per invoice is added to flat view
with f as (
  select
    SupplierInvoiceId
    , FileName
    , FileURL
    , row_number() over (partition by SupplierInvoiceId order by FileName) rn
  from {{ ref('fortnox_bi_dim_supplier_invoice_files_staging') }}
)

select
  i.OrgId
  , cs.OrgName
  , i.*
  except(
    OrgId
    , SupplierInvoiceId
    , SupplierId
  )
  , s.Name SupplierName
  , s.SupplierNumber
  , f.FileName
  , f.FileURL
from {{ ref('fortnox_bi_fact_supplier_invoices_staging') }} i
left join {{ ref('fortnox_bi_dim_company_staging') }} cs 
  on i.OrgId = cs.OrgId
left join {{ ref('fortnox_bi_dim_suppliers_staging') }} s 
  on i.SupplierId = s.SupplierId
left join f
  on f.SupplierInvoiceId = i.SupplierInvoiceId
  and rn=1