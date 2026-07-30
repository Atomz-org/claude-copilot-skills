{{ config(
    alias=(model_alias(model.name)),
        enabled = any_source_enabled(['fortnox'])
) }}

select
  'Supplier' DocumentType
  , SupplierInvoiceIdERP DocumentId
  , SupplierInvoiceNo DocumentNo
  , FileName
  , FileURL
  , DataSource
from {{ ref('erp_bi_dim_supplier_invoice_files') }}
order by 2