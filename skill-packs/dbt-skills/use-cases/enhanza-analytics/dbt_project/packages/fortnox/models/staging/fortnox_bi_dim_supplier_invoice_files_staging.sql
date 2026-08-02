{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  sif.SupplierInvoiceNumber SupplierInvoiceNo
  , sif.Name FileName
  , sif.FileURL
  , sif.OrgId
  , sif.OrgId || '-' || {{ blank_to_null('sif.SupplierInvoiceNumber') }} SupplierInvoiceId
from
  {{ source('fortnox_api', 'supplier_invoice_file_connections') }} sif
left join {{ source('fortnox_api', 'supplier_invoices') }} si
on sif.SupplierInvoiceNumber = si.GivenNumber
where si.Cancelled is FALSE